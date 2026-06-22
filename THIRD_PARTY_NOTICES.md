# Third-Party Notices

This repository's own source code and bundled `data/my-ime-tech.skk`
dictionary are licensed under the MIT License. See `LICENSE`.

The repository does not include a prebuilt Docker image and does not vendor
`libkkc`, `kkc`, or upstream SKK dictionaries.

The optional `runtime/my-ime-kkc-runtime` submodule is a separate GPL runtime
distribution repository. It may contain prebuilt GPL runtime bundles for users
who want to run my-ime without Docker or local libkkc builds. Those bundles are
not MIT-licensed my-ime source files; they are distributed under their own GPL
and third-party notices in that repository.

## Runtime Components Installed By Dockerfile

The provided `Dockerfile` installs the following Debian packages at image build
time:

```text
libkkc-utils
libkkc-data
```

Those packages pull in the `libkkc` runtime used by the `kkc` command.

Based on the Debian package copyright files and upstream project metadata:

```text
libkkc / libkkc-utils: GPL-3.0-or-later
libkkc-data: GPL-3.0-or-later
```

Upstream:

```text
https://github.com/ueno/libkkc
```

When users build the Docker image locally from this repository, those GPL
components are obtained from the operating system package repositories and are
not part of this repository's MIT-licensed source distribution.

If a prebuilt Docker image or other binary bundle containing those packages is
redistributed, the redistributor is responsible for complying with the
applicable GPL terms, including preserving license notices and providing the
corresponding source or a valid source offer as required by the GPL.

## SKK Dictionaries

The bundled `data/my-ime-tech.skk` file is a small project-local dictionary
created for my-ime and is MIT-licensed with this repository.

Do not copy entries from upstream SKK dictionary files into this repository
unless their licenses are checked and the resulting notice and license
obligations are documented here. Many common SKK dictionary packages are GPL or
mixed-license distributions.
