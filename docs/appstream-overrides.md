# Overriding screenshots in AppStream

How to make a local software centre show a different screenshot for a component,
and why the obvious approach does not work.

Established empirically on AppStream 1.1.3 (Fedora 44) and confirmed against
`src/as-component.c` at tag v1.1.3.

## Where catalogues are read from

`appstreamcli status` lists exactly two catalogue directories on Fedora:
`/usr/share/swcatalog/xml` and `/var/cache/swcatalog/xml`. There is **no
user-level path** — `~/.local/share/swcatalog/xml` is ignored even with
`XDG_DATA_HOME` set correctly.

Consequently a local override needs one root-owned write into
`/usr/share/swcatalog/xml/`, followed by `appstreamcli refresh --force`.

Discover does not need rebuilding; it reads the compiled AppStream cache. It
does read the pool at startup, so it must be restarted to pick up a change.

## What does not work: merge

The obvious approach is a catalogue containing a
`<component merge="replace">` that lists your own image URLs. It does not work.
The cache rebuilds without error, the file shows up in `appstreamcli status`,
and `appstreamcli dump` still returns the original screenshots.

The cause is in `as_component_merge_with_mode()`. In `replace` mode it copies
only `name`, `summary`, `description`, `pkgnames`, `bundles`, `icons` and
`provided`. Directly above the function sits the comment
`/* FIXME/TODO: We need to merge more attributes */`. Screenshots are not in the
list, so merge never touches them. This is a gap in the library, not a mistake
in the catalogue file.

Measured on an isolated pool holding one Fedora component and one of ours:

| Variant | Result |
|---|---|
| `merge="replace"` with `<screenshots>`, priority 0 / 1 / -1 | no change |
| `merge="append"` with `<screenshots>` | no change |
| `merge="replace"` with `<name>` | name replaced |
| `merge="remove-component"` | component disappears from the pool |
| full component, `priority="1"` | screenshots replaced |
| full component, no `priority` | no change |

The `<name>` and `remove-component` rows matter: they prove the merge machinery
itself is working, which is what narrows the problem down to the field list.

## What works: a full component at higher priority

Two requirements follow from the table.

**Publish a whole component, not a merge instruction.** `poc/make-override.py`
extracts the component from `fedora.xml.gz`, swaps its `<screenshots>` block and
writes it out under its own origin. Every other field is carried over unchanged,
so the store listing does not lose its description, categories or icons.

**`priority` is mandatory** and must exceed the distribution catalogue's.
`fedora.xml.gz` declares no `priority`, which means 0, so 1 is enough. File load
order does not matter — a `10-` prefix behaves identically to `90-`.

## Testing without touching the system

`AsPool.set_load_std_data_locations(False)` is not sufficient for isolation.
With the `LOAD_OS_CATALOG` flag set, the pool still loads the prebuilt system
cache from `/var/cache/swcatalog/cache/*.xb` and returns the distribution's full
component set.

This produced an entire round of worthless measurements: every variant appeared
to fail, because the harness was reporting the state of the system rather than
the contents of the directory it had been given. The tell was the component
count, 2369 where 2 were expected.

The correct setup is `set_flags(0)` together with
`add_extra_data_location(dir, FormatStyle.CATALOG)`. Always sanity-check the
harness first by including a component with an invented `<id>`: it must appear,
and it must be the only thing beside the component under test.

    import gi
    gi.require_version('AppStream', '1.0')
    from gi.repository import AppStream as A

    pool = A.Pool()
    pool.set_flags(0)
    pool.set_load_std_data_locations(False)
    pool.reset_extra_data_locations()
    pool.add_extra_data_location(directory, A.FormatStyle.CATALOG)
    pool.load()

Note that `get_components_by_id()` returns an `AsComponentBox`, which is not
iterable from Python; index it with `index_safe(i)` over `get_size()`.

## Worth reporting upstream

libappstream is silent when a merge instruction is ignored. `refresh` completes
without a warning, the file is counted in `status`, and the instruction simply
has no effect. Either the missing screenshot support is worth filing as a gap,
or the library should warn about fields outside the supported set.
