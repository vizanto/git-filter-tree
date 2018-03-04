"""
History rewrite helper script: Make ROOT the new initial commit and replace any
                               future files with ROOT contents

Usage:
    git-filter-tree prepend_root ROOT [-- REFS]

Arguments:

    ROOT        New root commit SHA
    REFS        git-rev-list options
"""

from .tree_filter import TreeFilter, Signature, cached, communicate, read_tree

class PrependRoot(TreeFilter):

    def __init__(self, new_parent):
        super().__init__()
        objs = communicate(['git', 'rev-list', new_parent])
        [sha1] = sorted(set(objs.splitlines()))
        self.new_parent = sha1
        tree = read_tree(self.repo, self.repo[sha1].tree_id)
        self.new_parent_tree = tree
        self.new_parent_files = frozenset(e[3] for e in tree)

    @cached
    async def rewrite_tree(self, obj):
        """Rewrite all folder items individually, recursive."""
        old_entries = list(await self.read_tree(obj.sha1))
        new_entries = self.new_parent_tree + [e for e in old_entries if not e[3] in self.new_parent_files]
        if new_entries != old_entries:
            sha1 = await self.write_tree(new_entries)
        else:
            sha1 = obj.sha1
        return [(obj.mode, obj.kind, sha1, obj.name)]

    @cached
    async def rewrite_root_commit(self, sha1):
        commit = self.repo[sha1]
        ids = [commit.tree_id] + commit.parent_ids
        tree, *parents = await self.rewrite_root_objects(ids)
        new_parent = self.new_parent
        return await self.create_commit( # http://www.pygit2.org/objects.html
            Signature(commit.author), Signature(commit.committer),
            commit.message, tree, [new_parent] if parents == [] else parents)


main = PrependRoot.main
if __name__ == '__main__':
    import sys; sys.exit(main())
