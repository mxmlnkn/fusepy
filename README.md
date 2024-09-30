# fusepy

``fusepy`` is a Python module that provides a simple interface to FUSE_ and
MacFUSE_. It's just one file and is implemented using ctypes.

fusepy requires FUSE 2.6 (or later) and runs on:

- Linux (i386, x86_64, PPC, arm64, MIPS)
- Mac OS X (Intel, PowerPC)
- FreeBSD (i386, amd64)


# Examples

See some examples of how you can use fusepy:

Example                          | Description
---------------------------------|-----------------------------
[memory](examples/memory.py)     | A simple memory filesystem
[loopback](examples/loopback.py) | A loopback filesystem
[context](examples/context.py)   | Sample usage of fuse_get_context()
[sftp](examples/sftp.py)         | A simple SFTP filesystem (requires paramiko)


# About this fork

This is basically a fork of [fusepy](https://github.com/fusepy/fusepy) because it did not see any development for over 6 years.
Copying the monolithic file into [ratarmount](https://github.com/mxmlnkn/ratarmount) is nice and easy and has no detriments because updates are not expected anyway.
[Refuse](https://github.com/pleiszenburg/refuse/) was an attempt to fork fusepy, but this attempt fizzled out only a month later. Among lots of metadata changes, it contains two bugfixes to the high-level API, which I'll simply redo in this fork.
See also the discussion in [this issue](https://github.com/mxmlnkn/ratarmount/issues/101).
I intend to maintain this fork as long as I maintain ratarmount, which is now over 5 years old.
For now, I have not uploaded to PyPI, so if you want to use this software, simply copy the license and `fuse.py` file into your project.
If there is any demand, I may upload this fork to PyPI.

The main motivations for forking are:

 - [x] FUSE 3 support. Based on the [libfuse changelog](https://github.com/libfuse/libfuse/blob/master/ChangeLog.rst#libfuse-300-2016-12-08), the amount of breaking changes should be fairly small. It should be possible to simply update these ten or so changed structs and functions in the existing fusepy.
 - [x] Translation layer performance. In benchmarks for a simple `find` call for listing all files, some callbacks such as `readdir` turned out to be significantly limited by converting Python dictionaries to ctype structs. The idea would be to expose the ctype structs to the fusepy caller.
   - Much of the performance was lost trying to populate the stat struct even though only the mode member is used by the kernel FUSE API.


# Platforms

While FUSE is (at least in the Unix world) a [Kernel feature](https://man7.org/linux/man-pages/man4/fuse.4.html), several user space libraries exist for easy access.
`libfuse` acts as the reference implementation.

 - [libfuse](https://github.com/libfuse/libfuse) (Linux, FreeBSD) (fuse.h [2](https://github.com/libfuse/libfuse/blob/fuse-2_9_bugfix/include/fuse.h) [3](https://github.com/libfuse/libfuse/blob/master/include/fuse.h))
 - [libfuse](https://github.com/openbsd/src/tree/master/lib/libfuse) (OpenBSD) (fuse.h [2](https://github.com/openbsd/src/blob/master/lib/libfuse/fuse.h))
 - [librefuse](https://github.com/NetBSD/src/tree/netbsd-8/lib/librefuse) (NetBSD) through [PUFFS](https://en.wikipedia.org/wiki/PUFFS_(NetBSD)) (fuse.h [2](https://github.com/NetBSD/src/blob/netbsd-8/lib/librefuse/fuse.h))
 - [FUSE for macOS](https://github.com/osxfuse/osxfuse) (OSX) (fuse.h [2](https://github.com/osxfuse/fuse/blob/master/include/fuse.h))
 - [MacFUSE](https://code.google.com/archive/p/macfuse/) (OSX), no longer maintained
 - [WinFsp](https://github.com/billziss-gh/winfsp) (Windows) (fuse.h [2](https://github.com/winfsp/winfsp/blob/master/inc/fuse/fuse.h) [3](https://github.com/winfsp/winfsp/blob/master/inc/fuse3/fuse.h))
 - [Dokany](https://github.com/dokan-dev/dokany) (Windows) (fuse.h [2](https://github.com/dokan-dev/dokany/blob/master/dokan_fuse/include/fuse.h))
 - [Dokan](https://code.google.com/archive/p/dokan/) (Windows), no longer maintained
