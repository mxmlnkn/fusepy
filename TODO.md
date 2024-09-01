# Open issues and PRs upstream

## Possibly valid bugs

 - [x] `#146 Bug: NameError: name 'self' is not defined`
 - [ ] `#144 How to enable O_DIRECT`
 - [x] `#142 FUSE::_wrapper() is a static method, so it shouldn't refer to 'self'`
 - [x] `#130 fixing TypeError: an integer is required when val is None`
 - [x] `#129 setattr(st, key, val): TypeError: an integer is required`
 - [x] `#124 "NameError: global name 'self' is not defined" in static FUSE._wrapper()`
 - [x] `#120 lock operation is passed a pointer to the flock strut`
 - [ ] `#116 Segfault when calling fuse_exit`
 - [ ] `#97 broken exception handling bug`
 - [x] `#81 Irritating default behavior of Operations class - raising FuseOSError(EROFS) where it really should not bug`

## Features

 - [x] `#147 Implement support for poll in the high-level API`
 - [x] `#145 Added fuse-t for Darwin search. See https://www.fuse-t.org/`
 - [x] `#127 Pass flags to create in non raw_fi mode.`
 - [ ] `#104 fix POSIX support for UTIME_OMIT and UTIME_NOW`
 - [x] `#101 Support init options and parameters.`
 - [x] `#100 libfuse versions`
 - [ ] `#70 time precision inside utimens causes rsync misses`
 - [x] `#66 Support init options and parameters`
 - [ ] `#61 performance with large numbers of files`
 - [x] `#28 Implement read_buf() and write_buf()`
 - [ ] `#7 fusepy speed needs`
 - [ ] `#2 Unable to deal with non-UTF-8 filenames`

## Cross-platform issues and feature requests that are out of scope

 - `#143 Expose a file system as case-insensitive`
 - `#141 Windows version?`
 - `#136 RHEL8 RPM package`
 - `#133 Slashes in filenames appear to cause "Input/output error"`
 - `#128 fusepy doesn't work when using 32bit personality`
 - `#117 Module name clash with python-fuse`
 - `#57 Does this support using the dokany fuse wrapper for use on Windows?`
 - [x] `#40 [openbsd] fuse_main_real not existing, there's fuse_main`

## Questions

 - `#138 “nothreads” argument explanation`
 - `#134 Project status?`
 - `#132 fusepy doesn't work when in background mode`
 - `#123 Create/Copy file with content`
 - `#119 Documentation`
 - `#118 Publish a new release`
 - `#115 read not returning 0 to client`
 - `#112 truncate vs ftruncate using python std library`
 - `#105 fuse_get_context() returns 0-filled tuple during release bug needs example`
 - `#98 Next steps/road map for the near future`
 - `#26 ls: ./mnt: Input/output error`

## FUSE-ll out of scope for me personally

 - `#114 [fusell] Allow userdata to be passed to constructor`
 - `#111 [fusell] Allow userdata to be set`
 - `#102 Extensions to fusell.`
 - `#85 bring system support in fusell.py to match fuse.py`

## Tests and documentation

 - `#139 Memory example empty files and ENOATTR`
 - `#127 package the LICENSE file in distributions`
 - `#109 Add test cases for fuse_exit implementation needs tests`
 - `#99 Python versions`
 - `#82 Create CONTRIBUTING.md`
 - `#80 Test infrastructure and suite`
 - `#78 update memory.py with mem.py from kungfuse?`
 - `#59 Include license text in its own file`
 - `#27 link to wiki from readme`

## Performance Improvement Ideas

 - Reduce wrappers:
   - [ ] Always forward path as bytes. This avoids the `_decode_optional_path` call completely.

## Changes for some real major version break

 - [ ] Enable `raw_fi` by default.
 - [ ] Remove file path encoding/decoding by default.
 - [ ] Return ENOSYS by default for almost all `Operations` implementation.
 - [ ] Simply expose `c_stat` to the fusepy user instead of expecting a badly documented dictionary.
       It is platform-dependent, but thanks to POSIX the core members are named identically.
       The order is unspecified by POSIX. What the current approach with `set_st_attrs` adds is silent
       ignoring of unknown keys. This may or may not be what one wants and the same can be achieved by
       testing `c_stat` with `hasattr` before setting values. This style guide should be documented.
