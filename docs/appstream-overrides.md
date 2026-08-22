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

## Live-system caveat: the isolated result did not render (2026-08-22)

The table above was measured in an **isolated** pool (`set_flags(0)` +
`add_extra_data_location`, one Fedora component + one of ours). On a **live**
Fedora Workstation with the OS catalogue cache loaded, the full-component
priority override behaved differently:

- With the separate `90-screenwright.xml.gz` (full component, `priority="1"`)
  installed and `appstreamcli refresh --force` run, **GNOME Software 50 still
  rendered the distribution's screenshot** in the carousel — not ours — even
  after a clean client-cache wipe (`gnome-software --quit` + `pkill -9` +
  `rm -rf ~/.cache/gnome-software ~/.local/share/gnome-software`). The store
  fetched only our thumbnail off the media server, yet drew the original. In the
  live pool `appstreamcli dump <id>` came back with **two** `<screenshot>`
  blocks (ours *and* the base), i.e. the screenshots were **unioned**, not
  replaced — the opposite of the isolated-pool row.

The most likely reason for the gap: in isolation the higher-priority component
*replaces* the lower-priority one wholesale (one wins, one is dropped), but in
the live system the base component comes from the precompiled
`/var/cache/swcatalog/cache/*.xb` and libappstream **merges the two same-id
components**, and for a list field like `<screenshots>` the merge is a union.
A clean numeric A/B on a fresh VM is still pending (the headless harness hit an
`appstreamcli dump`-returns-empty environment bug over SSH), so treat the exact
mechanism as open — but the **rendered outcome** is not in doubt.

### What renders in the live store: rewrite the base catalogue in place

The method proven to make GNOME Software actually draw our image is to **replace
the target component's `<screenshots>` inside the base catalogue itself**
(`/usr/share/swcatalog/xml/fedora.xml.gz`) and write the whole catalogue back —
no second component, so nothing to union. Implemented as
`domains/override.patch_catalog` and `cli override --patch`; it keeps every other
component intact. After this, `appstreamcli dump <id>` returns **exactly one**
screenshot (ours), and the carousel shows our marker (verified: crimson fraction
0.20 vs 0.0002 for the original — `docs/override-deploy.md`,
`images/cel2/cel2-PROOF-store-shows-ours.png`).

The trade-off: an in-place rewrite is overwritten by the next `fedora-appstream`
package update, so it is re-applied on each provision (the `deploy-override`
Ansible role does exactly this and asserts the one-screenshot outcome). For
screenwright's model — machines we provision and control — that is acceptable;
for a persistent third-party override the library gap (merge ignoring
screenshots) still wants an upstream fix.

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
