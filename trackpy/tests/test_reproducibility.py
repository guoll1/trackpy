from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import six
import os
import numpy as np
import pandas as pd
import pims
import nose
from numpy.testing import assert_array_equal, assert_allclose

import trackpy as tp
from trackpy.preprocessing import invert_image
from trackpy.utils import cKDTree, pandas_iloc
from trackpy.tests.common import assert_traj_equal, StrictTestCase

path, _ = os.path.split(os.path.abspath(__file__))
reproduce_fn = os.path.join(path, 'data', 'reproducibility_v0.4.npz')


def compare_pos_df(actual, expected, pos_atol=0.001, lost_atol=1):
    """Returns indices of equal and different positions inside dataframes
    `actual` and `expected`."""
    lost0 = []
    appeared1 = []
    dev0 = []
    dev1 = []
    equal0 = []
    equal1 = []
    for frame_no, expected_frame in expected.groupby('frame'):
        coords0 = expected_frame[['y', 'x']].values
        actual_frame = actual[actual['frame'] == frame_no]
        coords1 = actual_frame[['y', 'x']].values

        # use a KDTree to find nearest neighbors
        tree = cKDTree(coords1)
        devs, inds = tree.query(coords0)  # find nearest neighbors

        i_lost0 = np.argwhere(devs > lost_atol).ravel()
        # features that are equal
        i_equal0 = np.argwhere(devs < pos_atol).ravel()
        i_equal1 = inds[i_equal0]
        # features that are the same, but deviate in position
        i_dev0 = np.argwhere((devs < lost_atol) & (devs >= pos_atol)).ravel()
        i_dev1 = inds[i_dev0]
        # features that present in f1 and not in f0
        i_appeared1 = np.argwhere(~np.in1d(np.arange(len(coords1)),
                                           np.concatenate(
                                               [i_equal0, i_dev0]))).ravel()
        lost0.append(pandas_iloc(expected_frame, i_lost0).index.values)
        appeared1.append(pandas_iloc(actual_frame, i_appeared1).index.values)
        dev0.append(pandas_iloc(expected_frame, i_dev0).index.values)
        dev1.append(pandas_iloc(actual_frame, i_dev1).index.values)
        equal0.append(pandas_iloc(expected_frame, i_equal0).index.values)
        equal1.append(pandas_iloc(actual_frame, i_equal1).index.values)

    return np.concatenate(lost0), np.concatenate(appeared1), \
           (np.concatenate(dev0), np.concatenate(dev1)), \
           (np.concatenate(equal0), np.concatenate(equal1)),


class TestReproducibility(StrictTestCase):
    @classmethod
    def setUpClass(cls):
        super(TestReproducibility, cls).setUpClass()
        npz = np.load(reproduce_fn)
        cls.expected_find_raw = npz['arr_0']
        cls.expected_find_bp = npz['arr_1']
        cls.expected_refine = npz['arr_2']
        cls.expected_locate = npz['arr_3']
        cls.coords_link = npz['arr_4']
        cls.expected_link = npz['arr_5']
        cls.expected_link_memory = npz['arr_6']
        cls.expected_characterize = npz['arr_7']

        cls.v = pims.ImageSequence(os.path.join(path, 'video',
                                                'image_sequence', '*.png'))
        cls.v0_inverted = tp.invert_image(cls.v[0])

    def setUp(self):
        self.diameter = 9
        self.minmass = 140
        self.memory = 2
        self.bandpass_params = dict(lshort=1, llong=self.diameter)
        self.find_params = dict(separation=self.diameter)
        self.refine_params = dict(radius=int(self.diameter // 2))
        self.locate_params = dict(diameter=self.diameter, minmass=self.minmass,
                                  characterize=False)
        self.link_params = dict(search_range=5)
        self.characterize_params = dict(diameter=self.diameter,
                                        characterize=True)
        self.pos_columns = ['y', 'x']
        self.char_columns = ['mass', 'size', 'ecc', 'signal', 'raw_mass', 'ep']

    def test_find_raw(self):
        actual = tp.grey_dilation(self.v0_inverted, **self.find_params)
        assert_array_equal(actual, self.expected_find_raw)

    def test_find_bp(self):
        image_bp = tp.bandpass(self.v0_inverted, **self.bandpass_params)
        actual = tp.grey_dilation(image_bp, **self.find_params)
        assert_array_equal(actual, self.expected_find_bp)

    def test_refine(self):
        coords_v0 = self.expected_find_bp
        image_bp = tp.bandpass(self.v0_inverted, **self.bandpass_params)
        df = tp.refine_com(self.v0_inverted, image_bp, coords=coords_v0,
                           **self.refine_params)
        actual = df[df['mass'] >= self.minmass][self.pos_columns].values

        assert_allclose(actual, self.expected_refine)

    def test_locate(self):
        df = tp.locate(self.v0_inverted, **self.locate_params)
        actual = df[self.pos_columns].values
        assert_allclose(actual, self.expected_locate)

    def test_link_nomemory(self):
        expected = pd.DataFrame(self.coords_link,
                                columns=self.pos_columns + ['frame'])
        expected['frame'] = expected['frame'].astype(np.int)
        actual = tp.link(expected, **self.link_params)
        expected['particle'] = self.expected_link

        assert_traj_equal(actual, expected)

    def test_link_memory(self):
        expected = pd.DataFrame(self.coords_link,
                                columns=self.pos_columns + ['frame'])
        expected['frame'] = expected['frame'].astype(np.int)
        actual = tp.link(expected, memory=self.memory, **self.link_params)
        expected['particle'] = self.expected_link_memory

        assert_traj_equal(actual, expected)

    def test_characterize(self):
        df = tp.locate(self.v0_inverted, diameter=9)
        df = df[(df['x'] < 64) & (df['y'] < 64)]
        actual_coords = df[self.pos_columns].values
        actual_char = df[self.char_columns].values

        try:
            assert_allclose(actual_coords,
                            self.expected_characterize[:, :2])
        except AssertionError:
            raise AssertionError('The characterize tests failed as the coords'
                                 ' found by locate were not reproduced.')
        assert_allclose(actual_char,
                        self.expected_characterize[:, 2:])

# SCRIPT TO GENERATE THE FEATURES
# pos_columns = ['y', 'x']
# char_columns = ['mass', 'size', 'ecc', 'signal', 'raw_mass', 'ep']
# testpath = os.path.join(os.path.dirname(tp.__file__), 'tests')
# impath = os.path.join(testpath, 'video', 'image_sequence', '*.png')
# npzpath = os.path.join(testpath, 'data', 'reproducibility_v0.4.npz')
#
# v = pims.ImageSequence(impath)
# v0 = tp.invert_image(v[0])
# v0_bp = tp.bandpass(v0, lshort=1, llong=9)
# expected_find = tp.grey_dilation(v0, separation=9)
# expected_find_bandpass = tp.grey_dilation(v0_bp, separation=9)
# expected_refine = tp.refine_com(v0, v0_bp, radius=4,
#                                 coords=expected_find_bandpass)
# expected_refine = expected_refine[expected_refine['mass'] >= 140]
# expected_refine_coords = expected_refine[pos_columns].values
# expected_locate = tp.locate(v0, diameter=9, minmass=140)
# expected_locate_coords = expected_locate[pos_columns].values
# df = tp.locate(v0, diameter=9)
# df = df[(df['x'] < 64) & (df['y'] < 64)]
# expected_characterize = df[pos_columns + char_columns].values
#
# f = tp.batch(tp.invert_image(v), 9, minmass=140)
# f_crop = f[(f['x'] < 320) & (f['x'] > 280) & (f['y'] < 280) & (f['x'] > 240)]
# f_linked = tp.link(f_crop, search_range=5, memory=0)
# f_linked_memory = tp.link(f_crop, search_range=5, memory=2)
# link_coords = f_linked[pos_columns + ['frame']].values
# expected_linked = f_linked['particle'].values
# expected_linked_memory = f_linked_memory['particle'].values
#
# np.savez_compressed(npzpath, expected_find, expected_find_bandpass,
#                     expected_refine_coords, expected_locate_coords,
#                     link_coords, expected_linked, expected_linked_memory,
#                     expected_characterize)
