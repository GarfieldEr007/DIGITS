#!/usr/bin/env python2
# Copyright (c) 2015-2016, NVIDIA CORPORATION.  All rights reserved.
"""
Functions for creating temporary LMDBs
Used in test_views
"""

import os
import sys
import time
import argparse
from collections import defaultdict
from cStringIO import StringIO
import re
import random

import numpy as np
import PIL.Image
import lmdb

if __name__ == '__main__':
    dirname = os.path.dirname(os.path.realpath(__file__))
    sys.path.insert(0, os.path.join(dirname,'..','..'))
    from digits.config.load  import load_config
    load_config()

from digits import utils

# Run load_config() first to set the path to Caffe
import caffe.io
import caffe_pb2

IMAGE_SIZE  = 10
TRAIN_IMAGE_COUNT = 1000
VAL_IMAGE_COUNT = 1000
TEST_IMAGE_COUNT = 10


def create_lmdbs(folder, file_list, image_width=None, image_height=None, image_count=None):
    """
    Creates LMDBs for generic inference
    Returns the filename for a test image

    Creates these files in "folder":
        train_images/
        train_labels/
        val_images/
        val_labels/
        mean.binaryproto
        test.png
    """
    if image_width is None:
        image_width = IMAGE_SIZE
    if image_height is None:
        image_height = IMAGE_SIZE

    if image_count is None:
        train_image_count = TRAIN_IMAGE_COUNT
    else:
        train_image_count = image_count
    val_image_count = VAL_IMAGE_COUNT

    # read file list
    images = []
    f = open(file_list)
    for line in f.readlines():
        line = line.strip()
        if not line:
            continue

        path = None
        # might contain a numerical label at the end
        match = re.match(r'(.*\S)\s+(\d+)$', line)
        if match:
            path = match.group(1)
            ground_truth = int(match.group(2))
            images.append([path,ground_truth])

    print "Found %d image paths in image list" % len(images)

    for phase, image_count in [
            ('train', train_image_count),
            ('val', val_image_count)]:

        print "Will create %d pairs of %s images" % (image_count, phase)

        # create DBs
        image_db = lmdb.open(os.path.join(folder, '%s_images' % phase),
                map_async=True,
                max_dbs=0)
        label_db = lmdb.open(os.path.join(folder, '%s_labels' % phase),
                map_async=True,
                max_dbs=0)

        # add up all images to later create mean image
        image_sum = None
        shape = None

        # save test images (one for each label)
        testImagesSameClass = []
        testImagesDifferentClass = []

        for i in xrange(image_count):
            # pick up random indices from image list
            index1 = random.randint(0, len(images)-1)
            index2 = random.randint(0, len(images)-1)
            # label=1 if images are from the same class otherwise label=0
            label = 1 if int(images[index1][1]) == int(images[index2][1]) else 0
            # load images from files
            image1 = np.array(utils.image.load_image(images[index1][0]))
            image2 = np.array(utils.image.load_image(images[index2][0]))
            if not shape:
               # initialize image sum for mean image
               shape = image1.shape
               image_sum = np.zeros((3,shape[0],shape[1]), 'float64')
            assert(image1.shape == shape and image2.shape == shape)

            # create BGR image: blue channel will contain first image,
            # green channel will contain second image
            image_pair = np.zeros(image_sum.shape)
            image_pair[0] = image1
            image_pair[1] = image2

            image_sum += image_pair

            # save test images on first pass
            if label>0 and len(testImagesSameClass)<TEST_IMAGE_COUNT:
                testImagesSameClass.append(image_pair)
            if label==0 and len(testImagesDifferentClass)<TEST_IMAGE_COUNT:
                testImagesDifferentClass.append(image_pair)

            # encode into Datum object
            image = image_pair.astype('uint8')
            datum = caffe.io.array_to_datum(image, -1)
            # save to image DB
            _write_to_lmdb(image_db, str(i), datum.SerializeToString())

            # create label Datum
            label_datum = caffe_pb2.Datum()
            label_datum.channels, label_datum.height, label_datum.width = 1, 1, 1
            label_datum.float_data.extend(np.array([label]).flat)
            _write_to_lmdb(label_db, str(i), label_datum.SerializeToString())

            if i % (image_count/20) == 0:
                print "%d/%d" % (i, image_count)

        # close databases
        image_db.close()
        label_db.close()

        # save mean
        mean_image = (image_sum / image_count).astype('uint8')
        _save_mean(mean_image, os.path.join(folder, '%s_mean.binaryproto' % phase))

        # converting from BGR to RGB
        mean_image = mean_image[[2,1,0],...] # channel swap
        # convert to (height, width, channels)
        mean_image = mean_image.transpose((1,2,0))
        _save_mean(mean_image, os.path.join(folder, '%s_mean.png' % phase))

        # create test images
        for idx, image in enumerate(testImagesSameClass):
            _save_image(image, os.path.join(folder, '%s_test_same_class_%d.png' % (phase,idx)))
        for idx, image in enumerate(testImagesDifferentClass):
            _save_image(image, os.path.join(folder, '%s_test_different_class_%d.png' % (phase,idx)))

    return

def _write_to_lmdb(db, key, value):
    """
    Write (key,value) to db
    """
    success = False
    while not success:
        txn = db.begin(write=True)
        try:
            txn.put(key, value)
            txn.commit()
            success = True
        except lmdb.MapFullError:
            txn.abort()

            # double the map_size
            curr_limit = db.info()['map_size']
            new_limit = curr_limit*2
            print '>>> Doubling LMDB map size to %sMB ...' % (new_limit>>20,)
            db.set_mapsize(new_limit) # double it

def _save_image(image, filename):
    # converting from BGR to RGB
    image = image[[2,1,0],...] # channel swap
    # convert to (height, width, channels)
    image = image.astype('uint8').transpose((1,2,0))
    image = PIL.Image.fromarray(image)
    image.save(filename)

def _save_mean(mean, filename):
    """
    Saves mean to file

    Arguments:
    mean -- the mean as an np.ndarray
    filename -- the location to save the image
    """
    if filename.endswith('.binaryproto'):
        blob = caffe_pb2.BlobProto()
        blob.num = 1
        blob.channels = mean.shape[0]
        blob.height = mean.shape[1]
        blob.width = mean.shape[2]
        blob.data.extend(mean.astype(float).flat)
        with open(filename, 'wb') as outfile:
            outfile.write(blob.SerializeToString())

    elif filename.endswith(('.jpg', '.jpeg', '.png')):
        _save_image(mean, filename)
    else:
        raise ValueError('unrecognized file extension')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create-LMDB tool - DIGITS')

    ### Positional arguments

    parser.add_argument('folder',
            help='Where to save the images'
            )

    parser.add_argument('file_list',
            help='File list'
            )

    ### Optional arguments
    parser.add_argument('-c', '--image_count',
            type=int,
            help='How many images')

    args = vars(parser.parse_args())

    if os.path.exists(args['folder']):
        print 'ERROR: Folder already exists'
        sys.exit(1)
    else:
        os.makedirs(args['folder'])

    print 'Creating images at "%s" ...' % args['folder']

    start_time = time.time()

    create_lmdbs(args['folder'],
		 args['file_list'],
                 image_count=args['image_count'],
            )

    print 'Done after %s seconds' % (time.time() - start_time,)

