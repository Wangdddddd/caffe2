from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import tempfile
import unittest
import numpy as np
from caffe2.python import cnn, workspace, core

from caffe2.python.predictor_constants import predictor_constants as pc
import caffe2.python.predictor.predictor_exporter as pe
import caffe2.python.predictor.predictor_py_utils as pred_utils


class PredictorExporterTest(unittest.TestCase):
    def _create_model(self):
        m = cnn.CNNModelHelper()
        m.FC("data", "y",
             dim_in=5, dim_out=10,
             weight_init=m.XavierInit,
             bias_init=m.XavierInit)
        return m

    def setUp(self):
        np.random.seed(1)
        m = self._create_model()

        self.predictor_export_meta = pe.PredictorExportMeta(
            predict_net=m.net.Proto(),
            parameters=[str(b) for b in m.params],
            inputs=["data"],
            outputs=["y"],
            shapes={"y": (1, 10), "data": (1, 5)},
        )
        workspace.RunNetOnce(m.param_init_net)

        self.params = {
            param: workspace.FetchBlob(param)
            for param in self.predictor_export_meta.parameters}
        # Reset the workspace, to ensure net creation proceeds as expected.
        workspace.ResetWorkspace()

    def test_meta_constructor(self):
        '''
        Test that passing net itself instead of proto works
        '''
        m = self._create_model()
        pe.PredictorExportMeta(
            predict_net=m.net,
            parameters=m.params,
            inputs=["data"],
            outputs=["y"],
            shapes={"y": (1, 10), "data": (1, 5)},
        )

    def test_meta_net_def_net_runs(self):
        for param, value in self.params.items():
            workspace.FeedBlob(param, value)

        extra_init_net = core.Net('extra_init')
        extra_init_net.ConstantFill('data', 'data', value=1.0)
        pem = pe.PredictorExportMeta(
            predict_net=self.predictor_export_meta.predict_net,
            parameters=self.predictor_export_meta.parameters,
            inputs=self.predictor_export_meta.inputs,
            outputs=self.predictor_export_meta.outputs,
            shapes=self.predictor_export_meta.shapes,
            extra_init_net=extra_init_net,
        )

        db_type = 'minidb'
        db_file = tempfile.NamedTemporaryFile(
            delete=False, suffix=".{}".format(db_type))
        pe.save_to_db(
            db_type=db_type,
            db_destination=db_file.name,
            predictor_export_meta=pem)

        workspace.ResetWorkspace()

        meta_net_def = pe.load_from_db(
            db_type=db_type,
            filename=db_file.name,
        )

        self.assertTrue("data" not in workspace.Blobs())
        self.assertTrue("y" not in workspace.Blobs())

        init_net = pred_utils.GetNet(meta_net_def, pc.PREDICT_INIT_NET_TYPE)

        # 0-fills externalblobs blobs and runs extra_init_net
        workspace.RunNetOnce(init_net)

        self.assertTrue("data" in workspace.Blobs())
        self.assertTrue("y" in workspace.Blobs())

        print(workspace.FetchBlob("data"))
        np.testing.assert_array_equal(
            workspace.FetchBlob("data"), np.ones(shape=(1, 5)))
        np.testing.assert_array_equal(
            workspace.FetchBlob("y"), np.zeros(shape=(1, 10)))

        # Load parameters from DB
        global_init_net = pred_utils.GetNet(meta_net_def,
                                            pc.GLOBAL_INIT_NET_TYPE)
        workspace.RunNetOnce(global_init_net)

        # Run the net with a reshaped input and verify we are
        # producing good numbers (with our custom implementation)
        workspace.FeedBlob("data", np.random.randn(2, 5).astype(np.float32))
        predict_net = pred_utils.GetNet(meta_net_def, pc.PREDICT_NET_TYPE)
        workspace.RunNetOnce(predict_net)
        np.testing.assert_array_almost_equal(
            workspace.FetchBlob("y"),
            workspace.FetchBlob("data").dot(self.params["y_w"].T) +
            self.params["y_b"])

    def test_db_fails_without_params(self):
        with self.assertRaises(Exception):
            for db_type in ["minidb"]:
                db_file = tempfile.NamedTemporaryFile(
                    delete=False, suffix=".{}".format(db_type))
                pe.save_to_db(
                    db_type=db_type,
                    db_destination=db_file.name,
                    predictor_export_meta=self.predictor_export_meta)
