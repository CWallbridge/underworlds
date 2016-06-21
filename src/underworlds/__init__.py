

import time
import copy
import threading

from collections import deque

import logging
logger = logging.getLogger("underworlds.client")

from grpc.beta import implementations
import underworlds_pb2 as gRPC

from underworlds.types import World, Node, Situation

_TIMEOUT_SECONDS = 1
_INVALIDATION_PERIOD = 0.01 # 10 ms

#TODO: inherit for a collections.MutableSequence? what is the benefit?
class NodesProxy(threading.Thread):

    def __init__(self, context, world):
        threading.Thread.__init__(self)

        self._ctx = context # current underworlds context (useful to know the client name)
        self._world = world

        # This contains the tuple (id, world) and is used for identification
        # when communicating with the server
        self._server_ctx = gRPC.Context(client=self._ctx.id, world=self._world.name)

        self._len = self._ctx.rpc.getNodesLen(self._server_ctx, _TIMEOUT_SECONDS).size

        self._nodes = {} # node store

        # list of all node IDs that were once obtained.
        # They may be valid or invalid (if present in _updated_ids)
        self._ids = []

        # When I commit a node update, I get a notification from the
        # remote as any client. To prevent the reloading of the node I have
        # created myself, I store their ids in this list.
        self._ids_being_propagated = []

        # list of invalid ids (ie, nodes that have remotely changed).
        # This list is updated asynchronously from a server publisher
        self._updated_ids = deque(self._ctx.rpc.getNodesIds(self._server_ctx, _TIMEOUT_SECONDS).ids)

        self._deleted_ids = deque()

        # Get the root node
        self.rootnode = self._ctx.rpc.getRootNode(self._server_ctx, _TIMEOUT_SECONDS).id
        self._update_node_from_remote(self.rootnode)
        self._ids.append(self.rootnode)
 
        self.waitforchanges = threading.Condition()

        self._running = True
        self.cv = threading.Condition()

        self.start()

    def __del__(self):
        self._running = False

    def send(self, msg):

        req = {"client":self._ctx.id,
               "world": self._world.name,
               "req": msg}

        raise NotImplementedError(str(req))


    def _on_remotely_updated_node(self, id):

        if id not in self._updated_ids:
            self._updated_ids.append(id)

        self.waitforchanges.acquire()
        self.waitforchanges.notify_all()
        self.waitforchanges.release()

    def _on_remotely_deleted_node(self, id):

        self._len -= 1 # not atomic, but still fine since I'm the only one to write it
        self._deleted_ids.append(id)

        self.waitforchanges.acquire()
        self.waitforchanges.notify_all()
        self.waitforchanges.release()


    def _get_more_node(self):
        
        if not self._updated_ids:
            logger.warning("Slow propagation? Waiting for new/updated nodes notifications...")
            time.sleep(0.01) #leave some time for propagation

            # still empty? we have a problem!
            if not self._updated_ids:
                logger.error("Inconsistency detected! The server has not"\
                             " notified all the nodes updates. Or the "\
                             "IPC transport is really slow.")
                raise Exception()

        # here, _updated_ids is not empty. It should not raise an exception
        id = self._updated_ids.pop()

        self._get_node_from_remote(id)

    def _get_node_from_remote(self, id):

        nodeInCtxt = gRPC.NodeInContext(context=self._server_ctx,
                                        node=gRPC.Node(id=id))
        gRPCNode = self._ctx.rpc.getNode(nodeInCtxt, _TIMEOUT_SECONDS)

        self._ids.append(id)
        self._nodes[id] = Node.deserialize(gRPCNode)


    def _update_node_from_remote(self, id):

        nodeInCtxt = gRPC.NodeInContext(context=self._server_ctx,
                                        node=gRPC.Node(id=id))
        gRPCNode = self._ctx.rpc.getNode(nodeInCtxt, _TIMEOUT_SECONDS)

        updated_node = Node.deserialize(gRPCNode)
        self._nodes[id] = updated_node

        try:
            self._updated_ids.remove(id)
        except ValueError as ve:
            raise ve

    def __getitem__(self, key):

        # First, a bit of house keeping
        # do we have pending nodes to delete?
        if self._deleted_ids:
            tmp = copy.copy(self._deleted_ids)
            for id in tmp:
                try:
                    self._ids.remove(id)
                    del(self._nodes[id])
                    self._deleted_ids.remove(id)
                except ValueError:
                    logger.warning("The node %s is already removed. Feels like a synchro issue..." % id)

        # Then, let see what the user want:
        if type(key) is int:

            # First, are we over the lenght of our node list?
            if key >= self._len:
                raise IndexError

            # not downloaded enough nodes yet?
            while key >= len(self._ids):
                self._get_more_node()

            id = self._ids[key]

            # did the node changed since the last time we obtained it?
            if id in self._updated_ids:
                self._update_node_from_remote(id)

            return self._nodes[id]

        else: #assume it's a node ID

            if key in self._ids:
                # did the node changed since the last time we obtained it?
                if key in self._updated_ids:
                        self._update_node_from_remote(key)
                return self._nodes[key]

            else: # we do not have this node locally. Let's try to fetch it
                try:
                    self._get_node_from_remote(key)
                except ValueError:
                    #The node does not exist!!
                    raise KeyError("The node %s does not exist" % key)
                return self._nodes[key]

    def __len__(self):
        return self._len

    def append(self, node):
        """ Adds a new node to the node set.

        It is actually an alias for NodesProxy.update: all the restrictions
        regarding ordering or propagation time apply as well.
        """
        return self.update(node)

    def update(self, node):
        """ Update the value of a node in the node set.
        If the node does not exist yet, add it.

        This method sends the new/updated node to the
        remote. IT DOES NOT DIRECTLY modify the local
        copy of nodes: the roundtrip is slower, but data
        consistency is easier to ensure.

        This means that if you create or update a node, the
        node won't be created/updated immediately. It will 
        take some time (a couple of milliseconds) to propagate
        the change.

        Also, you have no guarantee regarding the ordering:

        for instance,

        >>> nodes.update(n1)
        >>> nodes.update(n2)

        does not mean that nodes[0] = n1 and nodes[1] = n2.
        This is due to the lazy access process.

        However, once accessed once, nodes keep their index (until a
        node with a smaller index is removed).

        """
        self._ctx.rpc.updateNode(gRPC.NodeInContext(context=self._server_ctx,
                                                    node=node.serialize(gRPC.Node)),
                                 _TIMEOUT_SECONDS)

    def remove(self, node):
        """ Deletes a node from the node set.

        THIS METHOD DOES NOT DIRECTLY delete the local
        copy of the node: it tells instead the server to
        delete this node for all clients.
        the roundtrip is slower, but data consistency is easier to ensure.

        This means that if you delete a node, the
        node won't be actually deleted immediately. It will 
        take some time (a couple of milliseconds) to propagate
        the change.
        """
        self._ctx.rpc.deleteNode(gRPC.NodeInContext(context=self._server_ctx,
                                                    node=node.serialize(gRPC.Node)),
                                 _TIMEOUT_SECONDS)


    def run(self):

        while self._running:
            time.sleep(_INVALIDATION_PERIOD)

            for invalidation in self._ctx.rpc.getNodeInvalidations(self._server_ctx, _TIMEOUT_SECONDS):
                action, id = invalidation.type, invalidation.id

                if action == gRPC.UPDATE:
                    logger.debug("Server notification: update node: " + id)
                    self._on_remotely_updated_node(id)
                elif action == gRPC.NEW:
                    logger.debug("Server notification: add node: " + id)
                    self._len += 1 # not atomic, but still fine since I'm the only one to write it
                    self._on_remotely_updated_node(id)
                elif action == gRPC.DELETE:
                    logger.debug("Server notification: delete node: " + id)
                    self._on_remotely_deleted_node(id)
                else:
                    raise RuntimeError("Unexpected invalidation action")


class SceneProxy(object):

    def __init__(self, ctx, world):

        self._ctx = ctx # context

        self.nodes = NodesProxy(self._ctx, world)

    @property
    def rootnode(self):
        return self.nodes[self.nodes.rootnode]

    def waitforchanges(self, timeout = None):
        """ This method blocks until either the scene has
        been updated (a node has been either updated, 
        added or removed) or the timeout is over.

        :param timeout: timeout in seconds (float value)
        """
        self.nodes.waitforchanges.acquire()
        self.nodes.waitforchanges.wait(timeout)
        self.nodes.waitforchanges.release()


    def finalize(self):
        self.nodes._running = False
        self.nodes.join()


class TimelineProxy(threading.Thread):

    def __init__(self, ctx, world):

        threading.Thread.__init__(self)

        self._ctx = ctx # context
        self._world = world

        # This contains the tuple (id, world) and is used for identification
        # when communicating with the server
        self._server_ctx = gRPC.Context(client=self._ctx.id, world=self._world.name)

        self.origin = self._ctx.rpc.timelineOrigin(self._server_ctx, _TIMEOUT_SECONDS).time
        logger.info("Accessing world <%s> (initially created on  %s)"%(self._world.name, time.asctime(time.localtime(self.origin))))

        self.situations = []

        #### Threading related stuff
        self.waitforchanges = threading.Condition()
        self._running = True
        self.cv = threading.Condition()
        super(TimelineProxy, self).start()

        self._onchange_callbacks = []

    def __del__(self):
        self._running = False

    def _on_remotely_started_situation(self, sit, isevent = False):

        self.situations.append(sit)

        self._notifychange()

    def _on_remotely_ended_situation(self, id):

        for sit in self.situations:
            if sit.id == id:
                sit.endtime = time.time()
                break

        self._notifychange()

    def _notifychange(self):
        self.waitforchanges.acquire()
        self.waitforchanges.notify_all()

        for cb in self._onchange_callbacks:
            cb()

        self.waitforchanges.release()


    def start(self, situation):
        self._send("new_situation " + json.dumps(situation.serialize()))
        self._ctx.rpc.recv() # server send a "ack"

    def event(self, situation):
        self._send("event " + json.dumps(situation.serialize()))
        self._ctx.rpc.recv() # server send a "ack"

    def end(self, situation):
        self._send("end_situation " + situation.id)
        self._ctx.rpc.recv() # server send a "ack"

    def _send(self, msg):

        req = {"client":self._ctx.id,
               "world": self._world.name,
               "req": msg}

        self._ctx.rpc.send_json(req)

    def onchange(self, cb, remove = False):
        """ Register a callback to be invoked when the timeline is updated.

        :param cb: a Python callable
        :param remove: (default: False) if true, remove the callback instead
        """

        self.waitforchanges.acquire()
        if not remove:
            self._onchange_callbacks.append(cb)
        else:
            self._onchange_callbacks.remove(cb)

        self.waitforchanges.release()


    def waitforchanges(self, timeout = None):
        """ This method blocks until either the timeline has
        been updated (a situation has been either started or
        ended) or the timeout is over.

        :param timeout: timeout in seconds (float value)
        """
        self.waitforchanges.acquire()
        self.waitforchanges.wait(timeout)
        self.waitforchanges.release()

    def run(self):

        while self._running:
            time.sleep(_INVALIDATION_PERIOD)

            for invalidation in self._ctx.rpc.getTimelineInvalidations(self._server_ctx, _TIMEOUT_SECONDS):
                action, id = invalidation.type, invalidation.id

                if action == gRPC.EVENT:
                    logger.debug("Server notification: event: " + sit.id)
                    self._on_remotely_started_situation(id, isevent = True)
                if action == gRPC.START:
                    logger.debug("Server notification: situation start: " + sit.id)
                    self._on_remotely_started_situation(id, isevent = False)
                elif action == gRPC.END:
                    logger.debug("Server notification: situation end: " + arg)
                    self._on_remotely_ended_situation(id)
                else:
                    raise RuntimeError("Unexpected invalidation action")



    def finalize(self):
        self._running = False
        self.join()


class WorldProxy:

    def __init__(self, ctx, name):
    
        if not isinstance(name, str):
            raise TypeError("A world proxy must be initialized "
                            "with a string as name. Got %s instead." % type(name))

        self._ctx = ctx # context

        self._world = World(name)

        self.name = name
        self.scene = SceneProxy(self._ctx, self._world)
        self.timeline = TimelineProxy(self._ctx, self._world)

    def copy_from(self, world):
        """ Creates and/or replaces the content of the world with an exact copy
        of the given `world`.
        """
        req = {"client":self._ctx.id,
               "world": self._world.name,
               "req": "deepcopy %s" % (world.name)}

        self._ctx.rpc.send_json(req)
        self._ctx.rpc.recv() #ack

    def finalize(self):
        self.scene.finalize()
        self.timeline.finalize()

    def __str__(self):
        return self.name

class WorldsProxy:

    def __init__(self, ctx):

        self._ctx = ctx # context

        self._worlds = []

    def __getitem__(self, key):
        world = WorldProxy(self._ctx, key)
        self._worlds.append(world)
        return world

    def __setitem__(self, key, world):
        logger.error("Can not set a world")
        pass

    def __iter__(self):
        """To iterate over the existing worlds, first ask the server
        an up-to-date list of worlds, and yield worlds as much as needed.
        Doing so, worlds are lazily created.
        """
        topo = self._ctx.topology()
        for world in topo["worlds"]:
            yield self.__getitem__(world)

    def finalize(self):
        for w in self._worlds:
            logger.debug("Context [%s]: Closing world <%s>" % (self._ctx.name, w.name))
            w.finalize()

class Context(object):

    def __init__(self, name):

        self.name = name

        channel = implementations.insecure_channel('localhost', 50051)
        self.rpc = gRPC.beta_create_Underworlds_stub(channel)

        logger.info("Connecting to the underworlds server...")
        self.id = self.rpc.helo(gRPC.Name(name=name), _TIMEOUT_SECONDS).id

        logger.info("<%s> connected to the underworlds server." % self.name)

        self.worlds = WorldsProxy(self)

    def send(self, msg):

        req = {"client":self.id,
               "req": msg}

        raise NotImplementedError(str(req))

    def topology(self):
        """Returns the current topology to the underworlds environment.

        It returns a dictionary with two members:
        - 'clients': a dictionary with clients' names known to the system
        as keys, and a dictionary of {world name: (link type, timestamp of
        last activity)} as values.
        - 'worlds': a list of all worlds known to the system
        """
        self.send("get_topology")

        return self.rpc.recv_json()

    def uptime(self):
        """Returns the server uptime in seconds.
        """
        self.send("uptime")
        return self.rpc.recv_json()

    def push_mesh(self, id, vertices, faces, normals, colors = None, material = None):

        data = json.dumps(
            {"vertices": vertices,
             "faces": faces,
             "normals": normals,
             "colors": colors,
             "material": material})

        self.send("push_mesh %s %s" % (id, data))
        self.rpc.recv() # ack

    def mesh(self, id):
        self.send("get_mesh %s" % id)
        return self.rpc.recv_json()

    def has_mesh(self, id):
        self.send("has_mesh %s" % id)
        return self.rpc.recv_json()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        logger.info("Closing context [%s]..." % self.name)
        self.worlds.finalize()
        logger.info("The context [%s] is now closed." % self.name)

    def __repr__(self):
        return "Underworlds context for " + self.name
