#!/bin/bash -e
echo "underworlds CI setup and test"
echo "============================="
lsb_release -a; uname -a

python3 --version

UWDS_CLONE_PATH=`pwd`

# manually install assimp as the version packaged in trusty is too old
echo "Installing pyassimp"

cd ${HOME}

if [ ! -d "assimp" ]; then
    git clone --depth=1 https://github.com/assimp/assimp.git

    echo "Content of HOME"

    ls

    cd ${HOME}/assimp
    echo "Content of `pwd`:"
    ls

    mkdir -p ${HOME}/assimp/build
    cd ${HOME}/assimp/build
    echo "Current path: `pwd`"


    cmake -DCMAKE_INSTALL_PREFIX=/usr/local -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DASSIMP_BUILD_ASSIMP_TOOLS=OFF ..
    make -j4
    sudo make install

fi

cd ${HOME}/assimp/port/PyAssimp

# workaround for bug introduced in assimp's 33bd5cfcfb0f27794a333273b20b60a7a550d184
mkdir -p ../../lib


pip install .


################################################################################
################################################################################
echo "Build and install underworlds"
cd ${UWDS_CLONE_PATH}

pip install .

################################################################################
################################################################################
echo "Run tests"
cd testing

# launch all tests, except OpenGL tests
time python3 ./run_tests.py --nogl

