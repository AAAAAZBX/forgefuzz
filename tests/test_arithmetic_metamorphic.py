from pathlib import Path
import json
import tempfile
import unittest

import numpy as np

from fuzz.backends.ascendc import AscendCBackend, rewrite_arithmetic
from fuzz.backends.triton import TritonBackend, commute_arithmetic
from fuzz.bundle import CaseBundle
from fuzz.cli import main
from fuzz.config import load_config
from fuzz.pipeline import execute_stage


class ArithmeticMetamorphicTests(unittest.TestCase):
    def test_mutation_leaves_addressing_and_reference_unchanged(self):
        for operator in ('+', '*'):
            source = f'def fuzz_kernel():\n    offsets = pid * block + index\n    value = x {operator} y\n\ndef reference():\n    return x {operator} y\n'
            mutated, manifest = commute_arithmetic(source)
            self.assertEqual(mutated, source.replace(f'value = x {operator} y', f'value = y {operator} x'))
            self.assertEqual(manifest['before'], f'x {operator} y')
        with self.assertRaises(ValueError):
            commute_arithmetic('def fuzz_kernel():\n    value = x - y\n')

    def test_ascend_rewrites_observable_output_only(self):
        source = ('    Sub(output1, input1, input2, active_len); // node 0\n'
                  '    Sub(output5, output2, output4, active_len); // node 4\n'
                  '    AscendC::DataCopy(OutputGlobal, output5, tensor_len);\n')
        mutated, manifest = rewrite_arithmetic(source)
        self.assertIn('Sub(output1, input1, input2, active_len)', mutated)
        self.assertIn('AscendC::Muls(output5, output4, -1.0f, active_len)', mutated)
        self.assertIn('AscendC::Add(output5, output2, output5, active_len)', mutated)
        self.assertEqual(manifest['stored_output'], 'output5')
        with self.assertRaises(ValueError):
            rewrite_arithmetic(source.replace('Sub(output5', 'Add(output5'))
        with self.assertRaises(ValueError):
            rewrite_arithmetic(source.replace('output2, output4', 'output5, output4'))

    def test_ascend_real_arithmetic_emit(self):
        upstream = Path(__file__).resolve().parents[2] / 'fuzz_code_generation/generate_graph.py'
        if not upstream.is_file():
            self.skipTest('real AscendC project is unavailable')
        with tempfile.TemporaryDirectory() as raw:
            config = load_config(overrides={'ascend_nodes': 5, 'ascend_ops': 'Add,Sub,Mul',
                                           'oracle_mode': 'metamorphic',
                                           'ascend_arithmetic_rewrite': 'sub_add_neg'})
            ctx = CaseBundle.create(Path(raw), 'ascend', 'ascendc', 10, config)
            backend = AscendCBackend()
            self.assertTrue(execute_stage(backend, ctx, 'generate').success)
            self.assertTrue(execute_stage(backend, ctx, 'emit').success)
            manifest = json.loads((ctx.work_dir / 'configs/metamorphic.json').read_text())
            self.assertEqual(manifest['rule'], 'sub_add_neg')
            self.assertEqual(manifest['stored_output'], 'output5')

    def test_oracle_compares_variant_and_detects_corruption(self):
        with tempfile.TemporaryDirectory() as raw:
            config = load_config(overrides={'oracle_mode': 'metamorphic'})
            ctx = CaseBundle.create(Path(raw), 'oracle', 'triton', 42, config)
            base = np.array([1, 2, 3], dtype=np.float32)
            np.save(ctx.work_dir / 'outputs/triton_npu.npy', base)
            np.save(ctx.work_dir / 'outputs/triton_reference.npy', base)
            np.save(ctx.work_dir / 'outputs/triton_variant_npu.npy', base)
            backend = TritonBackend()
            self.assertTrue(execute_stage(backend, ctx, 'oracle').success)
            np.save(ctx.work_dir / 'outputs/triton_variant_npu.npy', base + 1)
            result = execute_stage(backend, ctx, 'oracle')
            self.assertFalse(result.success)
            self.assertEqual(result.failure_kind, 'oracle_mismatch')
            (ctx.work_dir / 'outputs/triton_variant_npu.npy').unlink()
            self.assertEqual(execute_stage(backend, ctx, 'oracle').failure_kind, 'output_missing')

    def test_ascend_oracle_detects_corruption(self):
        with tempfile.TemporaryDirectory() as raw:
            config = load_config(overrides={'oracle_mode': 'metamorphic'})
            ctx = CaseBundle.create(Path(raw), 'binary-oracle', 'ascendc', 10, config)
            base = np.array([1, -2, 3], dtype=np.float32)
            base.tofile(ctx.work_dir / 'outputs/ascend_base.bin')
            base.tofile(ctx.work_dir / 'outputs/ascend_variant.bin')
            backend = AscendCBackend()
            self.assertTrue(execute_stage(backend, ctx, 'oracle').success)
            (base + 1).tofile(ctx.work_dir / 'outputs/ascend_variant.bin')
            result = execute_stage(backend, ctx, 'oracle')
            self.assertFalse(result.success)
            self.assertEqual(result.failure_kind, 'oracle_mismatch')

    def test_create_then_real_generate_emit(self):
        upstream = Path(__file__).resolve().parents[2] / 'triton-fuzzer-main/triton_ascend_fuzz'
        if not upstream.is_dir():
            self.skipTest('real Triton project is unavailable')
        with tempfile.TemporaryDirectory() as raw:
            for op in ('add', 'mul'):
                self.assertEqual(main(['create', '--backend', 'triton', '--seed', '42', '--case-id', op,
                                       '--output-dir', raw, '--template', f'elementwise_{op}',
                                       '--oracle-mode', 'metamorphic']), 0)
                case = Path(raw) / op
                self.assertFalse((case / 'program/kernel_spec.json').exists())
                self.assertEqual(main(['stage', 'generate', str(case)]), 0)
                self.assertEqual(main(['stage', 'emit', str(case)]), 0)
                variant = (case / 'source/variant/kernel.py').read_text()
                self.assertIn('value = y ' + ('+' if op == 'add' else '*') + ' x', variant)
                self.assertEqual(json.loads((case / 'configs/metamorphic.json').read_text())['rule'], 'arithmetic_commutativity')
