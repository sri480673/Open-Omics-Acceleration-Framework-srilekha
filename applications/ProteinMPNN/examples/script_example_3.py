#!/usr/bin/env python
# encoding: utf-8
import os
from subprocess import run
from argparse import ArgumentParser

def main(argv):
    # Argument parsing
    parser = ArgumentParser(description="Run protein folding on specific PDB and chains")
    parser.add_argument('--pdb_path', help="Path to the PDB file", default="/ProteinMPNN/inputs/PDB_complexes/pdbs/3HTN.pdb")
    parser.add_argument('--chains_to_design', help="Chains to design (space-separated)", default="A")
    parser.add_argument('--output', help="Output directory", default="/outputs/example_3_outputs")
    parser.add_argument('--num_seq_per_target', type=int, default=2, help="Number of sequences per target")
    parser.add_argument('--sampling_temp', type=float, default=0.1, help="Sampling temperature")
    parser.add_argument('--seed', type=int, default=37, help="Random seed")
    parser.add_argument('--batch_size', type=int, default=1, help="Batch size")
    parser.add_argument('--precision', choices=['float32', 'bfloat16'], default='float32', help="Precision type for calculations")
    args = parser.parse_args()

    # Check and create output directory if it doesn't exist
    output_dir = args.output
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    pdb_path = args.pdb_path

    # Run protein folding script
    a = run([
        'python', 'protein_mpnn_run.py',
        '--pdb_path', pdb_path,
        '--pdb_path_chains', args.chains_to_design,
        '--out_folder', output_dir,
        '--num_seq_per_target', str(args.num_seq_per_target),
        '--sampling_temp', str(args.sampling_temp),
        '--seed', str(args.seed),
        '--batch_size', str(args.batch_size),
        '--precision', args.precision
    ])
    assert a.returncode == 0, "Error running protein folding script"

if __name__ == "__main__":
    import sys
    main(sys.argv)
