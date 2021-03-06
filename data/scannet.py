from pathlib import Path
from PIL import Image, ImageOps,ImageDraw
import numpy as np
import xml.etree.ElementTree as ET
import random
import pickle
import torch
import sys
import os
from utils.config import cfg

train_anno_path = cfg.WIREFRAME.TRAIN_KEY_POINT_DIR
train_img_path = cfg.WIREFRAME.TRAIN_IMAGE_DIR
test_img_path = cfg.WIREFRAME.TEST_IMAGE_DIR
test_anno_path = cfg.WIREFRAME.TEST_KEY_POINT_DIR


class Scannet:
    def __init__(self, sets, obj_resize):
        """
        :param sets: 'train' or 'test'
        :param obj_resize: resized object size
        """
        self.classes = ["line"]
        if (sets == "train"):
            anno_path = train_anno_path
            img_path = train_img_path
        else:
            anno_path = test_anno_path
            img_path = test_img_path
        self.anno_path = Path(anno_path)
        self.img_path = Path(img_path)
        self.obj_resize = obj_resize
        self.sets = sets
        with open(anno_path,"r") as f:
            anno_list=f.readlines()
            anno_list=[item.strip() for item in anno_list]
            self.anno_list = anno_list
        with open(img_path,"r") as f:
            img_list=f.readlines()
            img_list=[item.strip() for item in img_list]
            self.img_list=img_list
        self.length=len(self.img_list)

    def get_pair(self, idx,cls=None, shuffle=True):
        """
        Randomly get a pair of objects from VOC-Berkeley keypoints dataset
        :param cls: None for random class, or specify for a certain set
        :param shuffle: random shuffle the keypoints
        :return: (pair of data, groundtruth permutation matrix)
        """
        dataset_len=len(self.anno_list)
        if (self.sets == "train"):
            idx = random.randint(0, dataset_len - 1)
        anno_pair = []
        #idx=random.randint(0,dataset_len-1)
        anno_name=self.anno_list[idx]
        img_name=self.img_list[idx]
        annos_list=anno_name.split(" ")
        img_list=img_name.split(" ")
        for anno_name,img_name in zip(annos_list,img_list):
            anno_dict = self.__get_anno_dict(anno_name, img_name)
            if(shuffle):
                random.shuffle(anno_dict['keypoints'])
            anno_pair.append(anno_dict)

        anno_pair[0]['keypoints'],anno_pair[1]['keypoints']=\
            self.select_lines(anno_pair[0]['keypoints'],anno_pair[1]['keypoints'])
        if(self.sets=="train"):
            perm_mat = np.zeros([len(_['keypoints'])+1 for _ in anno_pair], dtype=np.float32)
        else:
            perm_mat = np.zeros([len(_['keypoints']) for _ in anno_pair], dtype=np.float32)
        len1 = len(anno_pair[0]['keypoints'])
        len2 = len(anno_pair[1]['keypoints'])

        row_list = []
        col_list = []
        for i, keypoint in enumerate(anno_pair[0]['keypoints']):
            for j, _keypoint in enumerate(anno_pair[1]['keypoints']):
                if keypoint[0] == _keypoint[0]:
                    perm_mat[i, j] = 1
                    row_list.append(i)
                    col_list.append(j)
                    break

        row_list.sort()
        col_list.sort()
        if(self.sets=="train"):
            for idx in range(len1):
                if(idx not in row_list):
                    perm_mat[idx,-1]=1
            for idx in range(len2):
                if(idx not in col_list):
                    perm_mat[-1,idx]=1

        return anno_pair, perm_mat,None
    def select_lines(self,keypoint1,keypoint2):
        len1 = len(keypoint1)
        len2 = len(keypoint2)

        row_list = []
        col_list = []
        for i, keypoint in enumerate(keypoint1):
            for j, _keypoint in enumerate(keypoint2):
                if keypoint[0] == _keypoint[0]:
                    row_list.append(i)
                    col_list.append(j)
                    break
        outlier_row_idx, outlier_col_idx = [], []
        for idx in range(len1):
            if (idx not in row_list):
                outlier_row_idx.append(idx)
        for idx in range(len2):
            if (idx not in col_list):
                outlier_col_idx.append(idx)
        inlier1_num = len(row_list)
        inlier2_num = len(col_list)
        outlier1_num = len1-inlier1_num
        outlier2_num = len2-inlier2_num
        if(outlier1_num>inlier1_num):
            sample_num=random.randint(int(inlier1_num*0.5),min(outlier1_num,int(inlier1_num*1.5)))
            outlier_row_idx=random.sample(outlier_row_idx,sample_num)
        if(outlier2_num>inlier2_num):
            sample_num = random.randint(int(inlier2_num * 0.5), min(outlier2_num,int(inlier2_num*1.5)))
            outlier_col_idx=random.sample(outlier_col_idx,sample_num)

        res1,res2=[],[]
        for idx in row_list:
            res1.append(keypoint1[idx])
        for idx in outlier_row_idx:
            res1.append(keypoint1[idx])

        for idx in col_list:
            res2.append(keypoint2[idx])
        for idx in outlier_col_idx:
            res2.append(keypoint2[idx])
        random.shuffle(res1)
        random.shuffle(res2)
        filter_line1,filter_line2=[],[]

        return res1, res2

    def __get_anno_dict(self, anno_name,img_name):
        """
        Get an annotation dict from xml file
        """
        anno_file = Path(anno_name)
        assert anno_file.exists(), '{} does not exist.'.format(anno_file)

        img_file = Path(img_name)

        with Image.open(img_file) as img:
            height = img.height
            width = img.width
            old_size = (width, height)
            ratio = float(self.obj_resize[0]) / max(old_size)
            new_size = tuple([int(x * ratio) for x in old_size])
            obj = img.resize(new_size,resample=Image.BICUBIC)
            delta_w = self.obj_resize[0] - new_size[0]
            delta_h = self.obj_resize[1] - new_size[1]
            padding = (delta_w // 2, delta_h // 2, delta_w - (delta_w // 2), delta_h - (delta_h // 2))
            obj = ImageOps.expand(obj, padding)

        keypoint_list = []
        with open(str(anno_file.absolute()), "r") as anno:
            all_keypts = anno.readlines()
            all_keypts = [i.split(" ") for i in all_keypts]

            for keypoint in all_keypts:
                keypoint[1] = float(keypoint[1]) * ratio + delta_w // 2
                keypoint[3] = float(keypoint[3]) * ratio + delta_w // 2
                keypoint[2] = float(keypoint[2]) * ratio + delta_h // 2
                keypoint[4] = float(keypoint[4]) * ratio + delta_h // 2
                keypoint_list.append(keypoint)

        anno_dict = dict()
        anno_dict['image'] = obj
        anno_dict['keypoints'] = keypoint_list
        anno_dict['ori_sizes'] = old_size

        return anno_dict


if __name__ == '__main__':
    dataset = WireFrame('train', (512, 512))
    a = dataset.get_pair()
    pass
