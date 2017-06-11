"""
Utility module for git tree-rewrites.
"""

import multiprocessing
import os
import sys
import time

from collections import namedtuple
from subprocess import Popen, PIPE
from itertools import starmap


class Object(namedtuple('Object', ['mode', 'kind', 'sha1', 'name'])):

    path = ()
    parent = None

    def child(self, mode, kind, sha1, name):
        obj = Object(mode, kind, sha1, name)
        obj.path = self.path + (name,)
        obj.parent = self
        return obj

    def __hash__(self):
        # Can't use Object.__hash__ because it seems impossible to override in
        # multiprocessing scenarios (globals don't get transferred), even
        # subclassing seems to be broken…
        raise NotImplementedError


def communicate(args, text=None):
    text = text.encode('utf-8') if text else None
    proc = Popen(args, stdin=PIPE, stdout=PIPE)
    return proc.communicate(text)[0].decode('utf-8')


def read_tree(sha1):
    """Iterate over tuples (mode, kind, sha1, name)."""
    cmd = "git ls-tree {}"
    return (line.rstrip('\r\n').split(maxsplit=3)
            for line in os.popen(cmd.format(sha1.strip())))


def write_tree(entries):
    """Create a tree and return the hash."""
    #print(list(entries))
    text = '\n'.join(starmap('{} {} {}\t{}'.format, entries))
    args = ['git', 'mktree']
    return communicate(args, text).strip()


def write_blob(text):
    args = ['git', 'hash-object', '-w', '-t', 'blob', '--stdin']
    return communicate(args, text).strip()


def cached(func):
    cache = multiprocessing.Manager().dict()
    def wrapper(self, *args):
        key = self._hash(*args)
        if key not in cache:
            cache[key] = func(self, *args)
        return cache[key]
    wrapper.__name__ = func.__name__
    return wrapper


def time_to_str(seconds):
    return time.strftime('%H:%M:%S', time.gmtime(seconds))


class TreeFilter(object):

    @cached
    def get_root(self, sha1):
        sha1 = sha1.strip()
        root = Object('040000', 'tree', sha1, '')
        (new_mode, new_kind, new_sha1, new_name), = \
            self.rewrite_root(root)
        with open('objmap/'+sha1, 'w') as f:
            f.write(new_sha1)
        return new_sha1

    @cached
    def rewrite_root(self, obj):
        """Rewrite all folder items individually, recursive."""
        mode, kind, sha1, name = obj
        old_entries = list(read_tree(sha1))
        new_entries = [
            new_entry
            for old_entry in old_entries
            for new_entry in self.rewrite_object(obj.child(*old_entries))
        ]
        if new_entries != old_entries:
            sha1 = write_tree(new_entries)
        return [(mode, kind, sha1, name)]

    @cached
    def rewrite_object(self, obj):
        rewrite = self.rewrite_file if obj.kind == 'blob' else self.rewrite_tree
        return rewrite(obj)

    @cached
    def rewrite_file(self, obj):
        return [obj[:]]

    rewrite_tree = rewrite_root

    def depends(self, obj):
        # In general, we have to depend on all metadata + location
        return (obj[:], obj.path)

    def _hash(self, obj=None):
        return hash(self.depends(obj) if isinstance(obj, Object) else obj)

    def main(self, trees=None):
        if trees is None:
            trees = list(sys.stdin)

        os.makedirs('objmap', exist_ok=True)

        pool = multiprocessing.Pool(2*multiprocessing.cpu_count())

        pending = len(trees)
        done = 0
        tstart = time.time()
        checkpoint_done = 0
        checkpoint_time = tstart

        for _ in pool.imap_unordered(self.get_root, trees):
        #for _ in map(rewrite_roottree, trees):
            done += 1
            now = time.time()
            done_since_checkpoint = done - checkpoint_done
            compl_rate = (now - checkpoint_time) / done_since_checkpoint
            eta = time_to_str((pending - done) * compl_rate)
            print('\r{} / {} Trees rewritten ({:.1f} trees/sec), ETA: {}          '
                    .format(done, pending, 1 / compl_rate, eta), end='')
            sys.stdout.flush()
            # Keep a window of the last 5s of rewrites for ETA calculation.
            if now - checkpoint_time > 5:
                checkpoint_done = done
                checkpoint_time = now

        pool.close()
        pool.join()

        elapsed = time.time() - tstart
        print('\nTree rewrite completed in {} ({:.1f} trees/sec)'
              .format(time_to_str(elapsed), done / elapsed), end='')
