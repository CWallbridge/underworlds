cmake_minimum_required(VERSION 2.8)

project(underworlds)

option(ENABLE_TESTS "Build unit-tests" ON)

SET(CMAKE_CXX_FLAGS "-std=c++11")

# for UUIDs
find_package(Boost 1.43.0 REQUIRED)
include_directories(${Boost_INCLUDE_DIRS})

find_package(PkgConfig)
pkg_check_modules(PROTOBUF protobuf)
include_directories(${PROTOBUF_INCLUDE_DIRS})
pkg_check_modules(GRPC grpc++)
include_directories(${GRPC_INCLUDE_DIRS})
link_directories(${GRPC_LIBRARY_DIRS})

find_package(OpenCV COMPONENTS core REQUIRED)
include_directories(${OpenCV_INCLUDE_DIRS})

include_directories(src/libuwds)

file(GLOB uwds_pb_src src/libuwds/*pb.cc)
add_library(uwds SHARED 
                src/libuwds/uwds.cpp 
                src/libuwds/scene.cpp 
                src/libuwds/nodes.cpp 
                src/libuwds/node.cpp 
                ${uwds_pb_src})

add_executable( uwds_test src/libuwds/uwds_client.cpp )
target_link_libraries( uwds_test uwds ${PROTOBUF_LIBRARIES} ${GRPC_LIBRARIES} )

install (TARGETS uwds
         RUNTIME DESTINATION bin
         LIBRARY DESTINATION lib)

if(ENABLE_TESTS)
    enable_testing()
    add_subdirectory(testing/cpp)
endif()
