# ------------------------------------------------------------------------------
# multiview.pose3d.pytorch
# Copyright (c) 2018-present Microsoft
# Licensed under The Apache-2.0 License [see LICENSE for details]
# Written by Chunyu Wang (chnuwa@microsoft.com)
# ------------------------------------------------------------------------------

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os.path as osp
import numpy as np
import pickle
import collections

from dataset.joints_dataset_compatible import JointsDatasetCompatible
from utils.vis import save_all_preds


class MultiViewH36MCompatible(JointsDatasetCompatible):

    def __init__(self, cfg, image_set, is_train, transform=None):
        super().__init__(cfg, image_set, is_train, transform)
        self.actual_joints = {
            0: 'root',
            1: 'rhip',
            2: 'rkne',
            3: 'rank',
            4: 'lhip',
            5: 'lkne',
            6: 'lank',
            7: 'belly',
            8: 'neck',
            9: 'nose',
            10: 'head',
            11: 'lsho',
            12: 'lelb',
            13: 'lwri',
            14: 'rsho',
            15: 'relb',
            16: 'rwri'
        }

        anno_file = osp.join(self.root, 'h36m', 'annot',
                             'h36m_{}.pkl'.format(image_set))
        self.db = self.load_db(anno_file)

        self.u2a_mapping = self.get_mapping()
        super().do_mapping()

        self.grouping = self.get_group(self.db)
        self.group_size = len(self.grouping)
        self.dataset_type = 'multiview_h36m'

    def index_to_action_names(self):
        return {
            2: 'Direction',
            3: 'Discuss',
            4: 'Eating',
            5: 'Greet',
            6: 'Phone',
            7: 'Photo',
            8: 'Pose',
            9: 'Purchase',
            10: 'Sitting',
            11: 'SittingDown',
            12: 'Smoke',
            13: 'Wait',
            14: 'WalkDog',
            15: 'Walk',
            16: 'WalkTwo'
        }

    def get_mapping(self):
        union_keys = list(self.union_joints.keys())
        union_values = list(self.union_joints.values())

        mapping = {k: '*' for k in union_keys}
        for k, v in self.actual_joints.items():
            if v in union_values:
                idx = union_values.index(v)
                key = union_keys[idx]
                mapping[key] = k
        special_u2a = {'thorax':'neck', 'upper neck':'nose', 'head top':'head'}
        for k, v in special_u2a.items():
            ukeys = union_keys[union_values.index(k)]
            akeys = list(self.actual_joints.keys())[list(self.actual_joints.values()).index(v)]
            mapping[ukeys] = akeys
        return mapping


    def load_db(self, dataset_file):
        with open(dataset_file, 'rb') as f:
            dataset = pickle.load(f)
            return dataset

    def get_group(self, db):
        grouping = {}
        nitems = len(db)
        for i in range(nitems):
            keystr = self.get_key_str(db[i])
            camera_id = db[i]['camera_id']
            if keystr not in grouping:
                grouping[keystr] = [-1, -1, -1, -1]
            grouping[keystr][camera_id] = i

        filtered_grouping = []
        for _, v in grouping.items():
            if np.all(np.array(v) != -1):
                filtered_grouping.append(v)

        if self.is_train:
            filtered_grouping = filtered_grouping[::5]
        else:
            filtered_grouping = filtered_grouping[::64]

        return filtered_grouping

    def __getitem__(self, idx):
        input, target, weight, meta = [], [], [], []
        items = self.grouping[idx]
        for item in items:
            i, t, w, m = super().__getitem__(item)
            input.append(i)
            target.append(t)
            weight.append(w)
            meta.append(m)
        return input, target, weight, meta

    def __len__(self):
        return self.group_size

    def get_key_str(self, datum):
        return 's_{:02}_act_{:02}_subact_{:02}_imgid_{:06}'.format(
            datum['subject'], datum['action'], datum['subaction'],
            datum['image_id'])

    def evaluate(self, pred, output_dir=None):
        pred = pred.copy()

        # headsize = self.image_size[0] / 10.0
        threshold = 0.5

        u2a = self.u2a_mapping
        u2a = {k:v  for k, v in u2a.items() if v != '*'}
        # sorted by union index
        sorted_u2a = sorted(u2a.items(), key=lambda x: x[0])
        u = np.array([mapping[0] for mapping in sorted_u2a])
        a = np.array([mapping[1] for mapping in sorted_u2a])

        gt = []
        scales = []
        for items in self.grouping:
            for item in items:
                gt.append(self.db[item]['joints_2d'])
                scales.append(self.db[item]['scale'])
        gt = np.array(gt)[:, u, :2]
        pred = pred[:, :, :2]
        headsizes = np.amax(np.array(scales), axis=1, keepdims=True) * 200 / 10.0  # [N, 1], may also be divided by 1.25

        distance = np.sqrt(np.sum((gt - pred)**2, axis=2))  # [N, njoints]
        detected = (distance <= headsizes * threshold)

        if output_dir is not None:
            image_names = []
            for items in self.grouping:
                for item in items:
                    image_names.append(self.db[item]['image'])
            save_all_preds(gt, pred, detected, image_names, 'h36m', output_dir)

        joint_detection_rate = np.sum(detected, axis=0) / np.float(gt.shape[0])

        name_values = collections.OrderedDict()
        joint_names = self.actual_joints
        for i in range(len(u2a)):
            name_values[joint_names[a[i]]] = joint_detection_rate[i]
        name_values['mean'] = np.mean(joint_detection_rate)
        return name_values, name_values['mean']
