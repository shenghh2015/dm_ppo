"""
A script which prints the training data according to the given sample index.

Note, that it's crucial that exactly the same corresponding arguments are passed as in the training script. Including the seed. Only then the random sequence from the generated by megatron .npy files will match.

Here is how to decipher the index file name:

meg-gpt2_oscar-combined_text_document_train_indexmap_100ns_1024sl_42s_sample_idx.npy

100ns = --train-samples 100
1024s = --seq-length 1024
42s   = --seed 42

So these 3 have to match the training to get the correct output from this script.

If you're working on the same machine that already has the indices generated during the training, you can also do a sanity check that it doesn't generate new .npy files for the 3 train .npy files (but it will still do it for 3 valid and 3 test .npy files since we feed it a hardcoded setup of size 0 for both valid and test datasets.)

`--sample-id-range` is for consumed samples, so if the gap of interest is between these 2 iterations:

 iteration     3848/  159576 | consumed samples:        75888 | elapsed time per iteration (ms): 14308.9 | learning rate: 2.102E-05 | global batch size:    32 | lm loss: 6.452862E+00 | loss scale: 32768.0 | grad norm: 262044.694 | num zeros: 0.0 | number of skipped iterations:   0 | number of nan iterations:   0 |
 iteration     3792/  159576 | consumed samples:        74096 | elapsed time per iteration (ms): 16474.9 | learning rate: 2.052E-05 | global batch size:    32 | lm loss: 6.404737E+00 | loss scale: 32768.0 | grad norm: 214321.235 | num zeros: 0.0 | number of skipped iterations:   0 | number of nan iterations:   0 |

You'd then use:

`--sample-id-range 75888 74096`

the larger the batch size, the larger the number of samples will be.

Below is an example bash script to print the data in sample index range 5-15:

```
source $six_ALL_CCFRWORK/code/tr1-13B/bigscience/train/tr1-13B-base/start-tr1-13B
MEGATRON_DEEPSPEED_REPO=$six_ALL_CCFRWORK/code/tr1-13B/Megatron-DeepSpeed-tr1-13B/

cd $MEGATRON_DEEPSPEED_REPO

VOCAB_FILE=$MEGATRON_DEEPSPEED_REPO/data/gpt2-vocab.json
MERGE_FILE=$MEGATRON_DEEPSPEED_REPO/data/gpt2-merges.txt
DATA_PATH=$six_ALL_CCFRWORK/datasets-custom/oscar-en/meg-gpt2_text_document

SEQ_LEN=2048

python tools/sample_idxs_to_text.py \
    --print-text \
    --sample-id-range 5 15 \
    --seed 42 \
    --train-samples 100 \
    --seq-length $SEQ_LEN \
    --data-path $DATA_PATH \
    --data-impl mmap \
    --tokenizer-type GPT2BPETokenizer \
    --vocab-file $VOCAB_FILE \
    --merge-file $MERGE_FILE
````

If you want tokens instead of text, remove `--print-text` and add `--print-tokens` (but you can have both). If you want full token dumps add `--all-tokens`

If you want the data written to a file add:

    --output-file output.txt

This script can be extended to support valid and tests datasets as well, but currently ignores those.

Again, the key 3 args to get right are:

    --seed 42 \
    --train-samples 100 \
    --seq-length $SEQ_LEN \

"""

import sys
import torch

from megatron import get_args
from megatron import get_tokenizer
from megatron import initialize_megatron
from megatron.data.data_samplers import build_pretraining_data_loader
from megatron.data.gpt_dataset import build_train_valid_test_datasets
from megatron.training import update_train_iters


def _add_network_size_args(parser):
  group = parser.add_argument_group(title='Get text from sample idxs.')
  group.add_argument(
      '--sample-id-range',
      type=int,
      nargs='+',
      required=True,
      help='The number of samples consumed. ex) --sample-id-range 1024 2048')
  group.add_argument('--all-tokens',
                     action='store_true',
                     help='Whether to dump all tokens per record')
  group.add_argument('--print-tokens',
                     action='store_true',
                     help='Whether to print tokens')
  group.add_argument('--print-text',
                     action='store_true',
                     help='Whether to print text')
  group.add_argument(
      '--output-file',
      help='path to file if the dump should be saved into a file')

  return parser


if __name__ == "__main__":

  # megatron requires args, which are irrelevant to a task at hand, but w/o which it won't start.
  # There prefill those and not require the user to enter them.
  required_irrelevant_args = """
    --num-layers 1
    --hidden-size 1
    --num-attention-heads 1
    --max-position-embeddings 1000000
    --eval-interval 1
    --eval-iters 1
    --micro-batch-size 1
    --global-batch-size 1
    """.split()
  sys.argv.extend(required_irrelevant_args)

  initialize_megatron(extra_args_provider=_add_network_size_args)

  args = get_args()
  tokenizer = get_tokenizer()
  update_train_iters(args)

  if not (args.print_tokens or args.print_text):
    raise ValueError(
        "Need to specify either --print_tokens or --print_text or both")

  if args.all_tokens and not args.print_tokens:
    raise ValueError("--all_tokens requires --print_tokens")

  train_ds, _, _ = build_train_valid_test_datasets(
      data_prefix=args.data_path,
      data_impl=args.data_impl,
      splits_string=args.split,
      train_valid_test_num_samples=[args.train_samples, 0, 0],
      seq_length=args.seq_length,
      seed=args.seed,
      skip_warmup=(not args.mmap_warmup))

  # fast forward to where we want to start sampling
  train_dataloader = build_pretraining_data_loader(train_ds,
                                                   args.sample_id_range[0])
  data_iterator = iter(train_dataloader)

  if args.all_tokens:
    torch.set_printoptions(threshold=2**20)

  if args.output_file is not None:
    print(f"*** Saving to {args.output_file}")
    fh = open(args.output_file, "w")
  else:
    print(f"*** Dumping to stdout")

  def write(msg):
    if args.output_file:
      fh.write(msg + "\n")
    else:
      print(msg)

  for i in range(args.sample_id_range[0], args.sample_id_range[1]):
    tokens = next(data_iterator)["text"][0]

    if args.print_tokens:
      write(f"{i} {tokens}")

    if args.print_text:
      trim_decode_tokens = tokenizer.detokenize(tokens.tolist())
      write(f"{i} {trim_decode_tokens}")

  if args.output_file is not None:
    print(f"*** Output saved in {args.output_file}")
    fh.close()

  print(
      f"*** {args.sample_id_range[1]-args.sample_id_range[0]} records dumped")
