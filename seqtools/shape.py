from typing import Sequence
import array
import bisect
from logging import warning
import itertools
try:
    from itertools import izip as zip  # pylint: disable=redefined-builtin
except ImportError:
    pass
from .utils import isint, clip, basic_getitem, basic_setitem


class Collation(Sequence):
    def __init__(self, sequences):
        self.sequences = sequences

        if not all([len(seq) == len(self.sequences[0])
                    for seq in self.sequences]):
            raise ValueError("all sequences should have the same length")

    def __len__(self):
        return len(self.sequences[0])

    @basic_getitem
    def __getitem__(self, item):
        return tuple([seq[item] for seq in self.sequences])

    @basic_setitem
    def __setitem__(self, key, value):
        for seq, val in zip(self.sequences, value):
            seq[key] = val

    def __iter__(self):
        return zip(*self.sequences)


def collate(sequences):
    """Returns a view on the collated/pasted/stacked sequences.

    The n'th element is a tuple of the n'th elements from each sequence.

    .. image:: _static/collate.png
       :alt: collate
       :width: 50%
       :align: center

    Example:

        >>> arr = collate([[ 1,   2,   3,   4],
        ...                ['a', 'b', 'c', 'd'],
        ...                [ 5,   6,   7,   8]])
        >>> arr[2]
        (3, 'c', 7)
    """
    return Collation(sequences)


class Concatenation(Sequence):
    def __init__(self, sequences):
        self.sequences = []
        for seq in sequences:
            if isinstance(seq, Concatenation):
                for subseq in seq.sequences:
                    self.sequences.append(subseq)
            else:
                self.sequences.append(seq)

        self.offsets = array.array(
            'L', [0] + [len(seq) for seq in self.sequences])
        for i in range(1, len(self.sequences) + 1):
            self.offsets[i] += self.offsets[i - 1]

    def __len__(self):
        return self.offsets[-1]

    @basic_getitem
    def __getitem__(self, key):
        target_seq = bisect.bisect(self.offsets, key) - 1
        seq = self.sequences[target_seq]
        offset = self.offsets[target_seq]
        return seq[key - offset]

    @basic_setitem
    def __setitem__(self, key, value):
        target_seq = bisect.bisect(self.offsets, key) - 1
        seq = self.sequences[target_seq]
        offset = self.offsets[target_seq]
        seq[key - offset] = value

    def __iter__(self):
        return itertools.chain(*self.sequences)


def concatenate(sequences):
    """Returns a view on the concatenated sequences.

    .. image:: _static/concatenate.png
       :alt: concatenate
       :width: 25%
       :align: center
    """
    return Concatenation(sequences)


class BatchView(Sequence):
    def __init__(self, sequence, batch_size,
                 drop_last=False, pad=None, collate_fn=None):
        self.sequence = sequence
        self.batch_size = batch_size
        self.drop_last = drop_last
        self.pad = pad
        self.collate_fn = collate_fn

        if drop_last and pad is not None:
            warning("pad value is ignored because drop_last is true")

    def __len__(self):
        if len(self.sequence) % self.batch_size > 0 and not self.drop_last:
            return len(self.sequence) // self.batch_size + 1
        else:
            return len(self.sequence) // self.batch_size

    @basic_getitem
    def __getitem__(self, key):
        result = self.sequence[
            key * self.batch_size:(key + 1) * self.batch_size]

        if key == (len(self) - 1) and self.pad is not None:
            pad_size = self.batch_size - len(self.sequence) % self.batch_size
            result = concatenate((result, [self.pad] * pad_size))

        if self.collate_fn is not None:
            result = self.collate_fn(result)

        return result

    @basic_setitem
    def __setitem__(self, key, value):
        start = key * self.batch_size
        if key == len(self.sequence) // self.batch_size:
            stop = start + len(self.sequence) % self.batch_size
            expected_value_size = len(self.sequence) % self.batch_size \
                if self.pad is not None else self.batch_size

        else:
            stop = (key + 1) * self.batch_size
            expected_value_size = self.batch_size

        if len(value) != expected_value_size:
            raise ValueError(self.__class__.__name__ + " only support "
                             "one-to-one assignment")

        for i, val in zip(range(start, stop), value):
            self.sequence[i] = val


def batch(sequence, k, drop_last=False, pad=None, collate_fn=None):
    """Returns a view of a sequence in groups of k items.

    .. image:: _static/batch.png
        :alt: batch
        :width: 25%
        :align: center

    Args:
        sequence (Sequence):
            The input sequence.
        k (int):
            Number of items by block.
        drop_last (bool):
            Wether the last block should be ignored if it contains less
            than k items. (default False)
        pad (Optional[any]):
            padding item value to use in order to increase the size of
            the last block to k elements, set to `None` to prevent
            padding and return an incomplete block anyways (default
            None).
        collate_fn (Callable[[Sequence], Sequence]):
            An optional function that takes a sequence of items and
            returns a consolidated batch.

    Returns:
        Sequence: A sequence of batches.
    """
    return BatchView(sequence, k, drop_last, pad, collate_fn)


class Unbatching:
    def __init__(self, sequence, batch_size, last_batch_size=0):
        self.sequence = sequence
        self.batch_size = batch_size
        self.last_batch_size = last_batch_size or batch_size

    def __len__(self):
        return max(0, len(self.sequence) - 1) * self.batch_size \
            + self.last_batch_size

    @basic_getitem
    def __getitem__(self, key):
        return self.sequence[key // self.batch_size][key % self.batch_size]

    def __iter__(self):
        return itertools.chain.from_iterable(self.sequence)


def unbatch(sequence, batch_size, last_batch_size=None):
    """Returns a view on the concatenation of batched items.

    Args:
        sequence (Sequence[Sequence]):
            A sequence of batches.
        batch_size (int):
            The size of the batches, except for the last one which can
            be smaller.
        last_batch_size (int):
            The size for the last batch if the batch size does not align
            to the sequence size (default 0).

    Returns:
        Sequence: The concatenation of all batches in `sequence`.
    """
    return Unbatching(sequence, batch_size, last_batch_size)


class Split(Sequence):
    def __init__(self, sequence, edges):
        size = len(sequence)

        if isint(edges):
            if size / (edges + 1) % 1 != 0:
                raise ValueError("edges must divide the size of the sequence")
            step = size // (edges + 1)
            self.starts = array.array('L', range(0, size, step))
            self.stops = array.array('L', range(step, size + 1, step))

        elif isint(edges[0]):
            self.starts = array.array('L')
            self.stops = array.array('L')
            for edge in edges:
                start = self.stops[-1] if len(self.stops) > 0 else 0
                stop = edge

                self.starts.append(clip(start, 0, size - 1))
                self.stops.append(clip(stop, 0, size))

            self.starts.append(self.stops[-1])
            self.stops.append(size)

        else:
            self.starts = array.array('L')
            self.stops = array.array('L')
            for start, stop in edges:
                self.starts.append(clip(start, 0, size - 1))
                self.stops.append(clip(stop, 0, size))

        self.sequence = sequence

    def __len__(self):
        return len(self.starts)

    @basic_getitem
    def __getitem__(self, key):
        return self.sequence[self.starts[key]:self.stops[key]]

    @basic_setitem
    def __setitem__(self, key, value):
        start, stop = self.starts[key], self.stops[key]
        if len(value) != stop - start:
            raise ValueError(
                self.__class__.__name__ +
                " only supports one-to-one assignment")

        self.sequence[start:stop] = value


def split(sequence, edges):
    """Splits a sequence into a succession of subsequences.

    Args:
        sequence (Sequence):
            Input sequence.
        edges (Sequence[int] or int or Sequence[Tuple[int, int]]):
            `edges` specifies how to split the sequence

            - A 1D array that contains the indexes where the sequence
              should be cut, the beginning and the end of the sequence
              are implicit.
            - An int specifies how many cuts of equal size should be
              done, in which case `edges + 1` must divide the length of
              the sequence.
            - An sequence of int tuples specifies the limits of
              subsequences.

    Returns:
        Sequence: A sequence of subsequences split accordingly.
    """
    return Split(sequence, edges)
