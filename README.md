Underworlds: Geometric & Temporal Representation for Robots
===========================================================


Description
-----------


Underworlds is a distributed and lightweight framework that aims at sharing
between clients parallel models of the physical world surrounding a robot.

The clients can be geometric reasoners (that compute topological relations
between objects), motion planner, event monitors, viewers... any software that
need to access a geometric (based on 3D meshes of objects) and/or temporal
(based on events) of the world.

One of the main specific feature of Underworlds is the ability to store many
parallel worlds: past models of the environment, future models, models with
some objects filtered out, models that are physically consistent, etc.

This package provides the library, and a small set of core clients that are
useful for inspection and debugging.

Installation
------------

```
> python setup.py install
```

Testing Underworlds
-------------------


- Start the `underworlds` daemon:

```
> underworlded start
```

- Load some model:
```
> uwds-load testing/res/monkey_mat.dae test
```

This loads 3 monkey heads in the 'test' world.

- Get a 3D view of this world:

```
> uwds-view test
```

This opens an OpenGL windows that display the content of the 'test' world. You can
click on meshes to move them with the keyboard.
