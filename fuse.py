# Copyright (c) 2012 Terence Honles <terence@honles.com> (maintainer)
# Copyright (c) 2008 Giorgos Verigakis <verigak@gmail.com> (author)
#
# Permission to use, copy, modify, and distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

# mypy: ignore-errors

from __future__ import print_function, absolute_import, division

import ctypes
import errno
import logging
import os
import warnings

from ctypes import (
    CFUNCTYPE,
    POINTER,
    c_char_p,
    c_byte,
    c_size_t,
    c_ssize_t,
    c_int,
    c_uint,
    c_uint64,
    c_void_p,
)
from ctypes.util import find_library
from platform import machine, system
from signal import signal, SIGINT, SIG_DFL, SIGTERM
from stat import S_IFDIR
from traceback import print_exc


try:
    from functools import partial
except ImportError:
    # http://docs.python.org/library/functools.html#functools.partial
    def partial(func, *args, **keywords):
        def newfunc(*fargs, **fkeywords):
            newkeywords = keywords.copy()
            newkeywords.update(fkeywords)
            return func(*(args + fargs), **newkeywords)

        newfunc.func = func
        newfunc.args = args
        newfunc.keywords = keywords
        return newfunc

try:
    basestring
except NameError:
    basestring = str

log = logging.getLogger("fuse")
_system = system()
_machine = machine()

if _system == 'Windows' or _system.startswith('CYGWIN'):
    # NOTE:
    #
    # sizeof(long)==4 on Windows 32-bit and 64-bit
    # sizeof(long)==4 on Cygwin 32-bit and ==8 on Cygwin 64-bit
    #
    # We have to fix up c_long and c_ulong so that it matches the
    # Cygwin (and UNIX) sizes when run on Windows.
    import sys
    if sys.maxsize > 0xffffffff:
        c_win_long = ctypes.c_int64
        c_win_ulong = ctypes.c_uint64
    else:
        c_win_long = ctypes.c_int32
        c_win_ulong = ctypes.c_uint32

if _system == 'Windows' or _system.startswith('CYGWIN'):
    class c_timespec(ctypes.Structure):
        _fields_ = [('tv_sec', c_win_long), ('tv_nsec', c_win_long)]
elif _system == 'OpenBSD':
    c_time_t = ctypes.c_int64
    class c_timespec(ctypes.Structure):
        _fields_ = [('tv_sec', c_time_t), ('tv_nsec', ctypes.c_long)]
else:
    class c_timespec(ctypes.Structure):
        _fields_ = [('tv_sec', ctypes.c_long), ('tv_nsec', ctypes.c_long)]

class c_utimbuf(ctypes.Structure):
    _fields_ = [('actime', c_timespec), ('modtime', c_timespec)]

class c_stat(ctypes.Structure):
    pass    # Platform dependent

# Beware that FUSE_LIBRARY_PATH path was unchecked! If it is set to libfuse3.so.3.14.0,
# then it will mount without error, but when trying to access the mount point, will give:
#     Uncaught exception from FUSE operation setxattr, returning errno.EINVAL:
#         'utf-8' codec can't decode byte 0xe8 in position 1: invalid continuation byte
#     Traceback (most recent call last):
#       File "fuse.py", line 820, in _wrapper
#         return func(*args, **kwargs) or 0
#                ^^^^^^^^^^^^^^^^^^^^^
#       File "fuse.py", line 991, in setxattr
#         name.decode(self.encoding),
#         ^^^^^^^^^^^^^^^^^^^^^^^^^^
#     UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe8 in position 1:
#     invalid continuation byte
_libfuse_path = os.environ.get('FUSE_LIBRARY_PATH')
if not _libfuse_path:
    if _system == 'Darwin':
        # libfuse dependency
        _libiconv = ctypes.CDLL(find_library('iconv'), ctypes.RTLD_GLOBAL)

        _libfuse_path = (find_library('fuse4x') or find_library('osxfuse') or
                         find_library('fuse') or find_library('fuse-t'))
    elif _system == 'Windows':
        try:
            import _winreg as reg
        except ImportError:
            import winreg as reg
        def Reg32GetValue(rootkey, keyname, valname):
            key, val = None, None
            try:
                key = reg.OpenKey(rootkey, keyname, 0, reg.KEY_READ | reg.KEY_WOW64_32KEY)
                val = str(reg.QueryValueEx(key, valname)[0])
            except WindowsError:
                pass
            finally:
                if key is not None:
                    reg.CloseKey(key)
            return val
        _libfuse_path = Reg32GetValue(reg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WinFsp", r"InstallDir")
        if _libfuse_path:
            _libfuse_path += r"bin\winfsp-%s.dll" % ("x64" if sys.maxsize > 0xffffffff else "x86")
    else:
        _libfuse_path = find_library('fuse')

if not _libfuse_path:
    raise EnvironmentError('Unable to find libfuse')
else:
    _libfuse = ctypes.CDLL(_libfuse_path)

if _system == 'Darwin' and hasattr(_libfuse, 'macfuse_version'):
    _system = 'Darwin-MacFuse'


def get_fuse_version(libfuse):
    version = libfuse.fuse_version()
    if version < 100:
        return version // 10, version % 10
    if version < 1000:
        return version // 100, version % 100
    raise AttributeError(f"Version {version} of found library {_libfuse._name} cannot be parsed!")

fuse_version_major, fuse_version_minor = get_fuse_version(_libfuse)
if fuse_version_major == 2 and fuse_version_minor < 6:
    raise AttributeError(
        f"Found library {_libfuse_path} is too old: {fuse_version_major}.{fuse_version_minor}. "
        "There have been several ABI breaks in each version. Libfuse < 2.6 is not supported!"
    )
if fuse_version_major != 2:
    raise AttributeError(
        f"Found library {_libfuse_path} has wrong major version: {fuse_version_major}. "
        "Expected FUSE 2!"
    )


if _system in ('Darwin', 'Darwin-MacFuse', 'FreeBSD'):
    ENOTSUP = 45

    c_dev_t = ctypes.c_int32
    c_fsblkcnt_t = ctypes.c_ulong
    c_fsfilcnt_t = ctypes.c_ulong
    c_gid_t = ctypes.c_uint32
    c_mode_t = ctypes.c_uint16
    c_off_t = ctypes.c_int64
    c_pid_t = ctypes.c_int32
    c_uid_t = ctypes.c_uint32
    setxattr_t = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_byte), ctypes.c_size_t, ctypes.c_int,
        ctypes.c_uint32)
    getxattr_t = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_byte),
        ctypes.c_size_t, ctypes.c_uint32)
    if _system == 'Darwin':
        c_stat._fields_ = [
            ('st_dev', c_dev_t),
            ('st_mode', c_mode_t),
            ('st_nlink', ctypes.c_uint16),
            ('st_ino', ctypes.c_uint64),
            ('st_uid', c_uid_t),
            ('st_gid', c_gid_t),
            ('st_rdev', c_dev_t),
            ('st_atimespec', c_timespec),
            ('st_mtimespec', c_timespec),
            ('st_ctimespec', c_timespec),
            ('st_birthtimespec', c_timespec),
            ('st_size', c_off_t),
            ('st_blocks', ctypes.c_int64),
            ('st_blksize', ctypes.c_int32),
            ('st_flags', ctypes.c_int32),
            ('st_gen', ctypes.c_int32),
            ('st_lspare', ctypes.c_int32),
            ('st_qspare', ctypes.c_int64)]
    else:
        c_stat._fields_ = [
            ('st_dev', c_dev_t),
            ('st_ino', ctypes.c_uint32),
            ('st_mode', c_mode_t),
            ('st_nlink', ctypes.c_uint16),
            ('st_uid', c_uid_t),
            ('st_gid', c_gid_t),
            ('st_rdev', c_dev_t),
            ('st_atimespec', c_timespec),
            ('st_mtimespec', c_timespec),
            ('st_ctimespec', c_timespec),
            ('st_size', c_off_t),
            ('st_blocks', ctypes.c_int64),
            ('st_blksize', ctypes.c_int32)]
elif _system == 'Linux':
    ENOTSUP = 95

    c_dev_t = ctypes.c_ulonglong
    c_fsblkcnt_t = ctypes.c_ulonglong
    c_fsfilcnt_t = ctypes.c_ulonglong
    c_gid_t = ctypes.c_uint
    c_mode_t = ctypes.c_uint
    c_off_t = ctypes.c_longlong
    c_pid_t = ctypes.c_int
    c_uid_t = ctypes.c_uint
    setxattr_t = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_byte), ctypes.c_size_t, ctypes.c_int)

    getxattr_t = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_byte), ctypes.c_size_t)

    if _machine == 'x86_64':
        c_stat._fields_ = [
            ('st_dev', c_dev_t),
            ('st_ino', ctypes.c_ulong),
            ('st_nlink', ctypes.c_ulong),
            ('st_mode', c_mode_t),
            ('st_uid', c_uid_t),
            ('st_gid', c_gid_t),
            ('__pad0', ctypes.c_int),
            ('st_rdev', c_dev_t),
            ('st_size', c_off_t),
            ('st_blksize', ctypes.c_long),
            ('st_blocks', ctypes.c_long),
            ('st_atimespec', c_timespec),
            ('st_mtimespec', c_timespec),
            ('st_ctimespec', c_timespec)]
    elif _machine == 'mips':
        c_stat._fields_ = [
            ('st_dev', c_dev_t),
            ('__pad1_1', ctypes.c_ulong),
            ('__pad1_2', ctypes.c_ulong),
            ('__pad1_3', ctypes.c_ulong),
            ('st_ino', ctypes.c_ulong),
            ('st_mode', c_mode_t),
            ('st_nlink', ctypes.c_ulong),
            ('st_uid', c_uid_t),
            ('st_gid', c_gid_t),
            ('st_rdev', c_dev_t),
            ('__pad2_1', ctypes.c_ulong),
            ('__pad2_2', ctypes.c_ulong),
            ('st_size', c_off_t),
            ('__pad3', ctypes.c_ulong),
            ('st_atimespec', c_timespec),
            ('__pad4', ctypes.c_ulong),
            ('st_mtimespec', c_timespec),
            ('__pad5', ctypes.c_ulong),
            ('st_ctimespec', c_timespec),
            ('__pad6', ctypes.c_ulong),
            ('st_blksize', ctypes.c_long),
            ('st_blocks', ctypes.c_long),
            ('__pad7_1', ctypes.c_ulong),
            ('__pad7_2', ctypes.c_ulong),
            ('__pad7_3', ctypes.c_ulong),
            ('__pad7_4', ctypes.c_ulong),
            ('__pad7_5', ctypes.c_ulong),
            ('__pad7_6', ctypes.c_ulong),
            ('__pad7_7', ctypes.c_ulong),
            ('__pad7_8', ctypes.c_ulong),
            ('__pad7_9', ctypes.c_ulong),
            ('__pad7_10', ctypes.c_ulong),
            ('__pad7_11', ctypes.c_ulong),
            ('__pad7_12', ctypes.c_ulong),
            ('__pad7_13', ctypes.c_ulong),
            ('__pad7_14', ctypes.c_ulong)]
    elif _machine == 'ppc':
        c_stat._fields_ = [
            ('st_dev', c_dev_t),
            ('st_ino', ctypes.c_ulonglong),
            ('st_mode', c_mode_t),
            ('st_nlink', ctypes.c_uint),
            ('st_uid', c_uid_t),
            ('st_gid', c_gid_t),
            ('st_rdev', c_dev_t),
            ('__pad2', ctypes.c_ushort),
            ('st_size', c_off_t),
            ('st_blksize', ctypes.c_long),
            ('st_blocks', ctypes.c_longlong),
            ('st_atimespec', c_timespec),
            ('st_mtimespec', c_timespec),
            ('st_ctimespec', c_timespec)]
    elif _machine == 'ppc64' or _machine == 'ppc64le':
        c_stat._fields_ = [
            ('st_dev', c_dev_t),
            ('st_ino', ctypes.c_ulong),
            ('st_nlink', ctypes.c_ulong),
            ('st_mode', c_mode_t),
            ('st_uid', c_uid_t),
            ('st_gid', c_gid_t),
            ('__pad', ctypes.c_uint),
            ('st_rdev', c_dev_t),
            ('st_size', c_off_t),
            ('st_blksize', ctypes.c_long),
            ('st_blocks', ctypes.c_long),
            ('st_atimespec', c_timespec),
            ('st_mtimespec', c_timespec),
            ('st_ctimespec', c_timespec)]
    elif _machine == 'aarch64':
        c_stat._fields_ = [
            ('st_dev', c_dev_t),
            ('st_ino', ctypes.c_ulong),
            ('st_mode', c_mode_t),
            ('st_nlink', ctypes.c_uint),
            ('st_uid', c_uid_t),
            ('st_gid', c_gid_t),
            ('st_rdev', c_dev_t),
            ('__pad1', ctypes.c_ulong),
            ('st_size', c_off_t),
            ('st_blksize', ctypes.c_int),
            ('__pad2', ctypes.c_int),
            ('st_blocks', ctypes.c_long),
            ('st_atimespec', c_timespec),
            ('st_mtimespec', c_timespec),
            ('st_ctimespec', c_timespec)]
    else:
        # i686, use as fallback for everything else
        c_stat._fields_ = [
            ('st_dev', c_dev_t),
            ('__pad1', ctypes.c_ushort),
            ('__st_ino', ctypes.c_ulong),
            ('st_mode', c_mode_t),
            ('st_nlink', ctypes.c_uint),
            ('st_uid', c_uid_t),
            ('st_gid', c_gid_t),
            ('st_rdev', c_dev_t),
            ('__pad2', ctypes.c_ushort),
            ('st_size', c_off_t),
            ('st_blksize', ctypes.c_long),
            ('st_blocks', ctypes.c_longlong),
            ('st_atimespec', c_timespec),
            ('st_mtimespec', c_timespec),
            ('st_ctimespec', c_timespec),
            ('st_ino', ctypes.c_ulonglong)]
elif _system == 'Windows' or _system.startswith('CYGWIN'):
    ENOTSUP = 129 if _system == 'Windows' else 134
    c_dev_t = ctypes.c_uint
    c_fsblkcnt_t = c_win_ulong
    c_fsfilcnt_t = c_win_ulong
    c_gid_t = ctypes.c_uint
    c_mode_t = ctypes.c_uint
    c_off_t = ctypes.c_longlong
    c_pid_t = ctypes.c_int
    c_uid_t = ctypes.c_uint
    setxattr_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_byte), ctypes.c_size_t, ctypes.c_int)
    getxattr_t = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_byte), ctypes.c_size_t)
    c_stat._fields_ = [
        ('st_dev', c_dev_t),
        ('st_ino', ctypes.c_ulonglong),
        ('st_mode', c_mode_t),
        ('st_nlink', ctypes.c_ushort),
        ('st_uid', c_uid_t),
        ('st_gid', c_gid_t),
        ('st_rdev', c_dev_t),
        ('st_size', c_off_t),
        ('st_atimespec', c_timespec),
        ('st_mtimespec', c_timespec),
        ('st_ctimespec', c_timespec),
        ('st_blksize', ctypes.c_int),
        ('st_blocks', ctypes.c_longlong),
        ('st_birthtimespec', c_timespec)]
elif _system == 'OpenBSD':
    ENOTSUP = 91
    c_dev_t = ctypes.c_int32
    c_uid_t = ctypes.c_uint32
    c_gid_t = ctypes.c_uint32
    c_mode_t = ctypes.c_uint32
    c_off_t = ctypes.c_int64
    c_pid_t = ctypes.c_int32
    c_ino_t = ctypes.c_uint64
    c_nlink_t = ctypes.c_uint32
    c_blkcnt_t = ctypes.c_int64
    c_blksize_t = ctypes.c_int32
    setxattr_t = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_byte), ctypes.c_size_t, ctypes.c_int)
    getxattr_t = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_byte),
        ctypes.c_size_t)
    c_fsblkcnt_t = ctypes.c_uint64
    c_fsfilcnt_t = ctypes.c_uint64
    c_stat._fields_ = [
        ('st_mode', c_mode_t),
        ('st_dev', c_dev_t),
        ('st_ino', c_ino_t),
        ('st_nlink', c_nlink_t),
        ('st_uid', c_uid_t),
        ('st_gid', c_gid_t),
        ('st_rdev', c_dev_t),
        ('st_atimespec', c_timespec),
        ('st_mtimespec', c_timespec),
        ('st_ctimespec', c_timespec),
        ('st_size', c_off_t),
        ('st_blocks', c_blkcnt_t),
        ('st_blksize', c_blksize_t),
        ('st_flags', ctypes.c_uint32),
        ('st_gen', ctypes.c_uint32),
        ('st_birthtimespec', c_timespec),
    ]
else:
    raise NotImplementedError('%s is not supported.' % _system)


if _system == 'FreeBSD':
    c_fsblkcnt_t = ctypes.c_uint64
    c_fsfilcnt_t = ctypes.c_uint64
    setxattr_t = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_byte), ctypes.c_size_t, ctypes.c_int)

    getxattr_t = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_byte), ctypes.c_size_t)

    class c_statvfs(ctypes.Structure):
        _fields_ = [
            ('f_bavail', c_fsblkcnt_t),
            ('f_bfree', c_fsblkcnt_t),
            ('f_blocks', c_fsblkcnt_t),
            ('f_favail', c_fsfilcnt_t),
            ('f_ffree', c_fsfilcnt_t),
            ('f_files', c_fsfilcnt_t),
            ('f_bsize', ctypes.c_ulong),
            ('f_flag', ctypes.c_ulong),
            ('f_frsize', ctypes.c_ulong)]
elif _system == 'Windows' or _system.startswith('CYGWIN'):
    class c_statvfs(ctypes.Structure):
        _fields_ = [
            ('f_bsize', c_win_ulong),
            ('f_frsize', c_win_ulong),
            ('f_blocks', c_fsblkcnt_t),
            ('f_bfree', c_fsblkcnt_t),
            ('f_bavail', c_fsblkcnt_t),
            ('f_files', c_fsfilcnt_t),
            ('f_ffree', c_fsfilcnt_t),
            ('f_favail', c_fsfilcnt_t),
            ('f_fsid', c_win_ulong),
            ('f_flag', c_win_ulong),
            ('f_namemax', c_win_ulong)]
else:
    class c_statvfs(ctypes.Structure):
        _fields_ = [
            ('f_bsize', ctypes.c_ulong),
            ('f_frsize', ctypes.c_ulong),
            ('f_blocks', c_fsblkcnt_t),
            ('f_bfree', c_fsblkcnt_t),
            ('f_bavail', c_fsblkcnt_t),
            ('f_files', c_fsfilcnt_t),
            ('f_ffree', c_fsfilcnt_t),
            ('f_favail', c_fsfilcnt_t),
            ('f_fsid', ctypes.c_ulong),
            # ('unused', ctypes.c_int),
            ('f_flag', ctypes.c_ulong),
            ('f_namemax', ctypes.c_ulong)]


if _system == 'Linux':
    # https://github.com/torvalds/linux/blob/20371ba120635d9ab7fc7670497105af8f33eb08/include/uapi/asm-generic/fcntl.h#L195
    class c_flock_t(ctypes.Structure):
        _fields_ = [
            ('l_type', ctypes.c_short),
            ('l_whence', ctypes.c_short),
            ('l_start', c_off_t),
            ('l_len', c_off_t),
            ('l_pid', c_pid_t),
            ('l_sysid', ctypes.c_long),  # not always present
        ]
elif _system == 'OpenBSD':
    # https://github.com/openbsd/src/blob/a465f6177bcfdb2ffa9f98c7ca0780392688fc0d/sys/sys/fcntl.h#L180
    class c_flock_t(ctypes.Structure):
        _fields_ = [
            ('l_start', c_off_t),            # starting offset
            ('l_len', c_off_t),              # len = 0 means until end of file
            ('l_pid', c_pid_t),              # lock owner
            ('l_type', ctypes.c_short),    # lock type: read/write, etc.
            ('l_whence', ctypes.c_short),  # type of l_start
        ]
else:
    c_flock_t = ctypes.c_void_p


class fuse_file_info(ctypes.Structure):
    _fields_ = [
        ('flags', ctypes.c_int),
        ('fh_old', ctypes.c_ulong),
        ('writepage', ctypes.c_int),
        ('direct_io', ctypes.c_uint, 1),      # Introduced in libfuse 2.4
        ('keep_cache', ctypes.c_uint, 1),     # Introduced in libfuse 2.4
        ('flush', ctypes.c_uint, 1),          # Introduced in libfuse 2.6
        ('nonseekable', ctypes.c_uint, 1),    # Introduced in libfuse 2.8
        ('flock_release', ctypes.c_uint, 1),  # Introduced in libfuse 2.9
        ('padding', ctypes.c_uint, 27),
        ('fh', ctypes.c_uint64),
        ('lock_owner', ctypes.c_uint64)]

class fuse_context(ctypes.Structure):
    _fields_ = [
        ('fuse', ctypes.c_void_p),
        ('uid', c_uid_t),
        ('gid', c_gid_t),
        ('pid', c_pid_t),
        ('private_data', ctypes.c_void_p),
        # Added in 2.8. Note that this is an ABI break because programs compiled against 2.7
        # will allocate a smaller struct leading to out-of-bound accesses when used for a 2.8
        # shared library! It shouldn't hurt the other way around to have a larger struct than
        # the shared library expects. The newer members will simply be ignored.
        ('umask', c_mode_t),
    ]

_libfuse.fuse_get_context.restype = ctypes.POINTER(fuse_context)


# FUSE_BUF_IS_FD    = (1 << 1),
# FUSE_BUF_FD_SEEK  = (1 << 2),
# FUSE_BUF_FD_RETRY = (1 << 3),
fuse_buf_flags = ctypes.c_int

class fuse_buf(ctypes.Structure):
    _fields_ = [
        ('size', ctypes.c_size_t),
        ('flags', fuse_buf_flags),
        ('mem', ctypes.c_void_p),
        ('fd', ctypes.c_int),
        ('pos', c_off_t),
    ]

class fuse_bufvec(ctypes.Structure):
    _fields_ = [
        ('count', ctypes.c_size_t),
        ('idx', ctypes.c_size_t),
        ('off', ctypes.c_size_t),
        ('buf', ctypes.POINTER(fuse_buf)),
    ]


class fuse_conn_info(ctypes.Structure):  # Added in 2.6 (ABI break of "init" from 2.5->2.6)
    _fields_ = [
        ('proto_major', ctypes.c_uint),
        ('proto_minor', ctypes.c_uint),
        ('async_read', ctypes.c_uint),
        ('max_write', ctypes.c_uint),
        ('max_readahead', ctypes.c_uint),
        ('capable', ctypes.c_uint),               # Added in 2.8
        ('want', ctypes.c_uint),                  # Added in 2.8
        ('max_background', ctypes.c_uint),        # Added in 2.9
        ('congestion_threshold', ctypes.c_uint),  # Added in 2.9
        ('reserved', ctypes.c_uint * 23),
    ]

fuse_pollhandle_p = ctypes.c_void_p  # Not exposed to API


_fuse_operations_fields = [
    ('getattr', CFUNCTYPE(c_int, c_char_p, POINTER(c_stat))),
    ('readlink', CFUNCTYPE(c_int, c_char_p, POINTER(c_byte), c_size_t)),
    ('getdir', c_void_p),    # Deprecated, use readdir
    ('mknod', CFUNCTYPE(c_int, c_char_p, c_mode_t, c_dev_t)),
    ('mkdir', CFUNCTYPE(c_int, c_char_p, c_mode_t)),
    ('unlink', CFUNCTYPE(c_int, c_char_p)),
    ('rmdir', CFUNCTYPE(c_int, c_char_p)),
    ('symlink', CFUNCTYPE(c_int, c_char_p, c_char_p)),
    ('rename', CFUNCTYPE(c_int, c_char_p, c_char_p)),
    ('link', CFUNCTYPE(c_int, c_char_p, c_char_p)),
    ('chmod', CFUNCTYPE(c_int, c_char_p, c_mode_t)),
    ('chown', CFUNCTYPE(c_int, c_char_p, c_uid_t, c_gid_t)),
    ('truncate', CFUNCTYPE(c_int, c_char_p, c_off_t)),
    ('utime', c_void_p),     # Deprecated, use utimens
    ('open', CFUNCTYPE(c_int, c_char_p, POINTER(fuse_file_info))),
    ('read', CFUNCTYPE(
        c_int, c_char_p, POINTER(c_byte),
        c_size_t, c_off_t, POINTER(fuse_file_info))),
    ('write', CFUNCTYPE(
        c_int, c_char_p, POINTER(c_byte),
        c_size_t, c_off_t, POINTER(fuse_file_info))),
    ('statfs', CFUNCTYPE(c_int, c_char_p, POINTER(c_statvfs))),
    ('flush', CFUNCTYPE(c_int, c_char_p, POINTER(fuse_file_info))),
    ('release', CFUNCTYPE(c_int, c_char_p, POINTER(fuse_file_info))),
    ('fsync', CFUNCTYPE(c_int, c_char_p, c_int, POINTER(fuse_file_info))),
    ('setxattr', setxattr_t),
    ('getxattr', getxattr_t),
    ('listxattr', CFUNCTYPE(c_int, c_char_p, POINTER(c_byte), c_size_t)),
    ('removexattr', CFUNCTYPE(c_int, c_char_p, c_char_p)),
]
if fuse_version_minor >= 3:
    _fuse_operations_fields += [
        ('opendir', CFUNCTYPE(c_int, c_char_p, POINTER(fuse_file_info))),
        ('readdir', CFUNCTYPE(
            c_int,
            c_char_p,
            c_void_p,
            CFUNCTYPE(c_int, c_void_p, c_char_p, POINTER(c_stat), c_off_t),
            c_off_t,
            POINTER(fuse_file_info))),
        ('releasedir', CFUNCTYPE(c_int, c_char_p, POINTER(fuse_file_info))),
        ('fsyncdir', CFUNCTYPE(c_int, c_char_p, c_int, POINTER(fuse_file_info))),
        ('init', CFUNCTYPE(c_void_p, POINTER(fuse_conn_info))),
        ('destroy', CFUNCTYPE(c_void_p, c_void_p)),
    ]
if fuse_version_minor >= 5:
    _fuse_operations_fields += [
        ('access', CFUNCTYPE(c_int, c_char_p, c_int)),
        ('create', CFUNCTYPE(c_int, c_char_p, c_mode_t, POINTER(fuse_file_info))),
        ('ftruncate', CFUNCTYPE(c_int, c_char_p, c_off_t, POINTER(fuse_file_info))),
        ('fgetattr', CFUNCTYPE(c_int, c_char_p, POINTER(c_stat), POINTER(fuse_file_info))),
    ]
if fuse_version_minor >= 6:
    _fuse_operations_fields += [
        ('lock', CFUNCTYPE(c_int, c_char_p, POINTER(fuse_file_info), c_int, POINTER(c_flock_t))),
        ('utimens', CFUNCTYPE(c_int, c_char_p, POINTER(c_utimbuf))),
        ('bmap', CFUNCTYPE(c_int, c_char_p, c_size_t, POINTER(c_uint64))),
    ]
if fuse_version_minor >= 8:
    _fuse_operations_fields += [
        ('flag_nullpath_ok', c_uint, 1),
        ('flag_nopath', c_uint, 1),
        ('flag_utime_omit_ok', c_uint, 1),
        ('flag_reserved', c_uint, 29),

        ('ioctl', CFUNCTYPE(
            c_int, c_char_p, c_uint, c_void_p,
            POINTER(fuse_file_info), c_uint, c_void_p),
        ),
    ]
if fuse_version_minor >= 9:
    _fuse_operations_fields += [
        ('poll', CFUNCTYPE(
            c_int, c_char_p, POINTER(fuse_file_info), fuse_pollhandle_p, POINTER(c_uint)),
        ),
        ('write_buf', CFUNCTYPE(
            c_int, c_char_p, POINTER(fuse_bufvec), c_off_t, POINTER(fuse_file_info)),
        ),
        ('read_buf', CFUNCTYPE(
            c_int, c_char_p, POINTER(POINTER(fuse_bufvec)),
            c_size_t, c_off_t, POINTER(fuse_file_info)),
        ),
        ('flock', CFUNCTYPE(c_int, c_char_p, POINTER(fuse_file_info), c_int)),
        ('fallocate', CFUNCTYPE(
            c_int, c_char_p, c_int, c_off_t, c_off_t, POINTER(fuse_file_info)),
        ),
    ]

class fuse_operations(ctypes.Structure):
    _fields_ = _fuse_operations_fields


if _system == "OpenBSD":
    def fuse_main_real(argc, argv, fuse_ops_v, sizeof_fuse_ops, ctx_p):
        return _libfuse.fuse_main(argc, argv, fuse_ops_v, ctx_p)
else:
    fuse_main_real =_libfuse.fuse_main_real

def time_of_timespec(ts, use_ns=False):
    if use_ns:
        return ts.tv_sec * 10 ** 9 + ts.tv_nsec
    else:
        return ts.tv_sec + ts.tv_nsec / 1E9

def set_st_attrs(st, attrs, use_ns=False):
    for key, val in attrs.items():
        if key in ('st_atime', 'st_mtime', 'st_ctime', 'st_birthtime'):
            timespec = getattr(st, key + 'spec', None)
            if timespec is None:
                continue

            if use_ns:
                timespec.tv_sec, timespec.tv_nsec = divmod(int(val), 10 ** 9)
            else:
                timespec.tv_sec = int(val)
                timespec.tv_nsec = int((val - timespec.tv_sec) * 1E9)
        elif getattr(st, key, None) is not None:
            setattr(st, key, val)


def fuse_get_context():
    'Returns a (uid, gid, pid) tuple'

    ctxp = _libfuse.fuse_get_context()
    ctx = ctxp.contents
    return ctx.uid, ctx.gid, ctx.pid


def fuse_exit():
    '''
    This will shutdown the FUSE mount and cause the call to FUSE(...) to
    return, similar to sending SIGINT to the process.

    Flags the native FUSE session as terminated and will cause any running FUSE
    event loops to exit on the next opportunity. (see fuse.c::fuse_exit)
    '''
    # OpenBSD doesn't have fuse_exit
    # instead fuse_loop() gracefully catches SIGTERM
    if _system == "OpenBSD":
        os.kill(os.getpid(), SIGTERM)
        return

    fuse_ptr = ctypes.c_void_p(_libfuse.fuse_get_context().contents.fuse)
    _libfuse.fuse_exit(fuse_ptr)


class FuseOSError(OSError):
    def __init__(self, errno):
        super(FuseOSError, self).__init__(errno, os.strerror(errno))


class FUSE(object):
    '''
    This class is the lower level interface and should not be subclassed under
    normal use. Its methods are called by fuse.

    Assumes API version 2.6 or later.
    '''

    OPTIONS = (
        ('foreground', '-f'),
        ('debug', '-d'),
        ('nothreads', '-s'),
    )

    def __init__(self, operations, mountpoint, raw_fi=False, encoding='utf-8',
                 **kwargs):

        '''
        Setting raw_fi to True will cause FUSE to pass the fuse_file_info
        class as is to Operations, instead of just the fh field.

        This gives you access to direct_io, keep_cache, etc.
        '''

        self.operations = operations
        self.raw_fi = raw_fi
        self.encoding = encoding
        self.__critical_exception = None

        self.use_ns = getattr(operations, 'use_ns', False)
        if not self.use_ns:
            warnings.warn(
                'Time as floating point seconds for utimens is deprecated!\n'
                'To enable time as nanoseconds set the property "use_ns" to '
                'True in your operations class or set your fusepy '
                'requirements to <4.',
                DeprecationWarning)

        args = ['fuse']

        args.extend(flag for arg, flag in self.OPTIONS
                    if kwargs.pop(arg, False))

        kwargs.setdefault('fsname', operations.__class__.__name__)
        args.append('-o')
        args.append(','.join(self._normalize_fuse_options(**kwargs)))
        args.append(mountpoint)

        args = [arg.encode(encoding) for arg in args]
        argv = (ctypes.c_char_p * len(args))(*args)

        fuse_ops = fuse_operations()
        for ent in fuse_operations._fields_:
            name, prototype = ent[:2]

            check_name = name

            # ftruncate()/fgetattr() are implemented in terms of their
            # non-f-prefixed versions in the operations object
            if check_name in ["ftruncate", "fgetattr"]:
                check_name = check_name[1:]

            val = getattr(operations, check_name, None)
            if val is None or getattr(val, 'libfuse_ignore', False):
                continue

            # Function pointer members are tested for using the
            # getattr(operations, name) above but are dynamically
            # invoked using self.operations(name)
            if hasattr(prototype, 'argtypes'):
                val = prototype(partial(self._wrapper, getattr(self, name)))

            setattr(fuse_ops, name, val)

        try:
            old_handler = signal(SIGINT, SIG_DFL)
        except ValueError:
            old_handler = SIG_DFL

        err = fuse_main_real(
            len(args), argv, ctypes.pointer(fuse_ops),
            ctypes.sizeof(fuse_ops),
            None)

        try:
            signal(SIGINT, old_handler)
        except ValueError:
            pass

        del self.operations     # Invoke the destructor
        if self.__critical_exception:
            raise self.__critical_exception
        if err:
            raise RuntimeError(err)

    @staticmethod
    def _normalize_fuse_options(**kargs):
        for key, value in kargs.items():
            if isinstance(value, bool):
                if value is True:
                    yield key
            else:
                yield '%s=%s' % (key, value)

    def _wrapper(self, func, *args, **kwargs):
        'Decorator for the methods that follow'

        try:
            if func.__name__ == "init":
                # init may not fail, as its return code is just stored as
                # private_data field of struct fuse_context
                return func(*args, **kwargs) or 0

            else:
                try:
                    return func(*args, **kwargs) or 0

                except OSError as e:
                    if isinstance(e.errno, int) and e.errno > 0:
                        log.debug(
                            "FUSE operation %s raised a %s, returning errno %s.",
                            func.__name__, type(e), e.errno, exc_info=True)
                        return -e.errno
                    else:
                        log.error(
                            "FUSE operation %s raised an OSError with negative "
                            "errno %s, returning errno.EINVAL.",
                            func.__name__, e.errno, exc_info=True)
                        return -errno.EINVAL

                except Exception:
                    log.error("Uncaught exception from FUSE operation %s, "
                              "returning errno.EINVAL.",
                              func.__name__, exc_info=True)
                    return -errno.EINVAL

        except BaseException as e:
            self.__critical_exception = e
            log.critical(
                "Uncaught critical exception from FUSE operation %s, aborting.",
                func.__name__, exc_info=True)
            # the raised exception (even SystemExit) will be caught by FUSE
            # potentially causing SIGSEGV, so tell system to stop/interrupt FUSE
            fuse_exit()
            return -errno.EFAULT

    def _decode_optional_path(self, path):
        # NB: this method is intended for fuse operations that
        #     allow the path argument to be NULL,
        #     *not* as a generic path decoding method
        if path is None:
            return None
        return path.decode(self.encoding)

    def getattr(self, path, buf):
        return self.fgetattr(path, buf, None)

    def readlink(self, path, buf, bufsize):
        ret = self.operations('readlink', path.decode(self.encoding)).encode(self.encoding)

        # copies a string into the given buffer
        # (null terminated and truncated if necessary)
        data = ctypes.create_string_buffer(ret[:bufsize - 1])
        ctypes.memmove(buf, data, len(data))
        return 0

    def mknod(self, path, mode, dev):
        return self.operations('mknod', path.decode(self.encoding), mode, dev)

    def mkdir(self, path, mode):
        return self.operations('mkdir', path.decode(self.encoding), mode)

    def unlink(self, path):
        return self.operations('unlink', path.decode(self.encoding))

    def rmdir(self, path):
        return self.operations('rmdir', path.decode(self.encoding))

    def symlink(self, source, target):
        'creates a symlink `target -> source` (e.g. ln -s source target)'

        return self.operations('symlink', target.decode(self.encoding),
                                          source.decode(self.encoding))

    def rename(self, old, new):
        return self.operations('rename', old.decode(self.encoding),
                                         new.decode(self.encoding))

    def link(self, source, target):
        'creates a hard link `target -> source` (e.g. ln source target)'

        return self.operations('link', target.decode(self.encoding),
                                       source.decode(self.encoding))

    def chmod(self, path, mode):
        return self.operations('chmod', path.decode(self.encoding), mode)

    def chown(self, path, uid, gid):
        # Check if any of the arguments is a -1 that has overflowed
        if c_uid_t(uid + 1).value == 0:
            uid = -1
        if c_gid_t(gid + 1).value == 0:
            gid = -1

        return self.operations('chown', path.decode(self.encoding), uid, gid)

    def truncate(self, path, length):
        return self.operations('truncate', path.decode(self.encoding), length)

    def open(self, path, fip):
        fi = fip.contents
        if self.raw_fi:
            return self.operations('open', path.decode(self.encoding), fi)
        else:
            fi.fh = self.operations('open', path.decode(self.encoding), fi.flags)
            return 0

    def read(self, path, buf, size, offset, fip):
        fh = fip.contents if self.raw_fi else fip.contents.fh
        ret = self.operations('read', self._decode_optional_path(path), size, offset, fh)

        if not ret:
            return 0

        retsize = len(ret)
        assert retsize <= size, \
            'actual amount read %d greater than expected %d' % (retsize, size)

        ctypes.memmove(buf, ret, retsize)
        return retsize

    def write(self, path, buf, size, offset, fip):
        data = ctypes.string_at(buf, size)
        fh = fip.contents if self.raw_fi else fip.contents.fh
        return self.operations('write', self._decode_optional_path(path), data, offset, fh)

    def statfs(self, path, buf):
        stv = buf.contents
        attrs = self.operations('statfs', path.decode(self.encoding))
        for key, val in attrs.items():
            if hasattr(stv, key):
                setattr(stv, key, val)

        return 0

    def flush(self, path, fip):
        fh = fip.contents if self.raw_fi else fip.contents.fh
        return self.operations('flush', self._decode_optional_path(path), fh)

    def release(self, path, fip):
        fh = fip.contents if self.raw_fi else fip.contents.fh
        return self.operations('release', self._decode_optional_path(path), fh)

    def fsync(self, path, datasync, fip):
        fh = fip.contents if self.raw_fi else fip.contents.fh
        return self.operations('fsync', self._decode_optional_path(path), datasync, fh)

    def setxattr(self, path, name, value, size, options, *args):
        return self.operations('setxattr', path.decode(self.encoding),
                               name.decode(self.encoding),
                               ctypes.string_at(value, size), options, *args)

    def getxattr(self, path, name, value, size, *args):
        ret = self.operations('getxattr', path.decode(self.encoding),
                                          name.decode(self.encoding), *args)

        retsize = len(ret)
        # allow size queries
        if not value:
            return retsize

        # do not truncate
        if retsize > size:
            return -errno.ERANGE

        # Does not add trailing 0
        buf = ctypes.create_string_buffer(ret, retsize)
        ctypes.memmove(value, buf, retsize)

        return retsize

    def listxattr(self, path, namebuf, size):
        attrs = self.operations('listxattr', path.decode(self.encoding)) or ''
        ret = '\x00'.join(attrs).encode(self.encoding)
        if len(ret) > 0:
            ret += '\x00'.encode(self.encoding)

        retsize = len(ret)
        # allow size queries
        if not namebuf:
            return retsize

        # do not truncate
        if retsize > size:
            return -errno.ERANGE

        buf = ctypes.create_string_buffer(ret, retsize)
        ctypes.memmove(namebuf, buf, retsize)

        return retsize

    def removexattr(self, path, name):
        return self.operations('removexattr', path.decode(self.encoding),
                                              name.decode(self.encoding))

    def opendir(self, path, fip):
        # Ignore raw_fi
        fip.contents.fh = self.operations('opendir', path.decode(self.encoding))
        return 0

    def readdir(self, path, buf, filler, offset, fip):
        # Ignore raw_fi
        for item in self.operations('readdir', self._decode_optional_path(path), fip.contents.fh):
            if isinstance(item, basestring):
                name, st, offset = item, None, 0
            else:
                name, attrs, offset = item
                if attrs:
                    st = c_stat()
                    set_st_attrs(st, attrs, use_ns=self.use_ns)
                else:
                    st = None

            if filler(buf, name.encode(self.encoding), st, offset) != 0:
                break

        return 0

    def releasedir(self, path, fip):
        # Ignore raw_fi
        return self.operations('releasedir', self._decode_optional_path(path), fip.contents.fh)

    def fsyncdir(self, path, datasync, fip):
        # Ignore raw_fi
        return self.operations('fsyncdir', self._decode_optional_path(path),
                                           datasync, fip.contents.fh)

    def init(self, conn):
        return self.operations('init', '/')

    def destroy(self, private_data):
        return self.operations('destroy', '/')

    def access(self, path, amode):
        return self.operations('access', path.decode(self.encoding), amode)

    def create(self, path, mode, fip):
        fi = fip.contents
        path = path.decode(self.encoding)

        if self.raw_fi:
            return self.operations('create', path, mode, fi)
        else:
            fi.fh = self.operations('create', path, mode, fi.flags)
            return 0

    def ftruncate(self, path, length, fip):
        fh = fip.contents if self.raw_fi else fip.contents.fh
        return self.operations('truncate', self._decode_optional_path(path), length, fh)

    def fgetattr(self, path, buf, fip):
        ctypes.memset(buf, 0, ctypes.sizeof(c_stat))

        st = buf.contents
        if fip:
            fh = fip.contents if self.raw_fi else fip.contents.fh
        else:
            fh = fip

        attrs = self.operations('getattr', self._decode_optional_path(path), fh)
        set_st_attrs(st, attrs, use_ns=self.use_ns)
        return 0

    def lock(self, path, fip, cmd, lock):
        fh = fip.contents if self.raw_fi else fip.contents.fh
        return self.operations('lock', self._decode_optional_path(path), fh, cmd, lock)

    def utimens(self, path, buf):
        if buf:
            atime = time_of_timespec(buf.contents.actime, use_ns=self.use_ns)
            mtime = time_of_timespec(buf.contents.modtime, use_ns=self.use_ns)
            times = (atime, mtime)
        else:
            times = None

        return self.operations('utimens', path.decode(self.encoding), times)

    def bmap(self, path, blocksize, idx):
        return self.operations('bmap', path.decode(self.encoding), blocksize, idx)

    def ioctl(self, path, cmd, arg, fip, flags, data):
        fh = fip.contents if self.raw_fi else fip.contents.fh
        return self.operations('ioctl', path.decode(self.encoding), cmd, arg, fh, flags, data)

    def poll(self, path, fip, ph, reventsp):
        fh = fip.contents if self.raw_fi else fip.contents.fh
        return self.operations('poll', path.decode(self.encoding), fh, ph, reventsp)

    def write_buf(self, path, buf, offset, fip):
        fh = fip.contents if self.raw_fi else fip.contents.fh
        return self.operations('write_buf', path.decode(self.encoding), buf, offset, fh)

    def read_buf(self, path, bufpp, size, offset, fip):
        fh = fip.contents if self.raw_fi else fip.contents.fh
        return self.operations('read_buf', path.decode(self.encoding), bufpp, size, offset, fh)

    def flock(self, path, fip, op):
        fh = fip.contents if self.raw_fi else fip.contents.fh
        return self.operations('flock', path.decode(self.encoding), fh, op)

    def fallocate(self, path, mode, offset, size, fip):
        fh = fip.contents if self.raw_fi else fip.contents.fh
        return self.operations('fallocate', path.decode(self.encoding), mode, offset, size, fh)


def _nullable_dummy_function(method):
    '''
    Marks the given method as to be ignored by the 'FUSE' class.
    This makes it possible to add methods with the self-documenting function signatures
    while still not giving any actual callbacks to libfuse as long as these methods are
    not overwritten by a method in a subclassed 'Operations' class.
    '''
    method.libfuse_ignore = True
    return method


class Operations(object):
    '''
    This class should be subclassed and passed as an argument to FUSE on
    initialization. All operations should raise a FuseOSError exception on
    error.

    When in doubt of what an operation should do, check the FUSE header file
    or the corresponding system call man page.

    Any method that is not overwritten will not be set up for libfuse.
    This has the side effect that libfuse can implement fallbacks in case
    callbacks are not implemented. For example 'read' will be used when 'read_buf'
    is not implemented.

    This has the side effect that trace debug output, enabled with -o debug,
    for these FUSE function will not be printed. To enable the debug output,
    it should be overwritten with a method simply raising FuseOSError(errno.ENOSYS).
    '''

    def __call__(self, op, *args):
        if not hasattr(self, op):
            raise FuseOSError(errno.EFAULT)
        return getattr(self, op)(*args)

    @_nullable_dummy_function
    def access(self, path, amode):
        return 0

    @_nullable_dummy_function
    def bmap(self, path, blocksize, idx):
        pass

    @_nullable_dummy_function
    def chmod(self, path, mode):
        raise FuseOSError(errno.EROFS)

    @_nullable_dummy_function
    def chown(self, path, uid, gid):
        raise FuseOSError(errno.EROFS)

    @_nullable_dummy_function
    def create(self, path, mode, fi=None):
        '''
        When raw_fi is False (default case), create should return a
        numerical file handle and the signature of create becomes:
          create(self, path, mode, flags)

        When raw_fi is True the file handle should be set directly by create
        and return 0.
        '''

        raise FuseOSError(errno.EROFS)

    @_nullable_dummy_function
    def destroy(self, path):
        'Called on filesystem destruction. Path is always /'

    @_nullable_dummy_function
    def flush(self, path, fh):
        return 0

    @_nullable_dummy_function
    def fsync(self, path, datasync, fh):
        return 0

    @_nullable_dummy_function
    def fsyncdir(self, path, datasync, fh):
        return 0

    # Either fgetattr or getattr must be non-null or else libfuse 2.6 will segfault
    # with auto-cache enabled. In FUSE 2.9.9, 3.16, setting this to nullptr, should work fine.
    # https://github.com/libfuse/libfuse/blob/0a0db26bd269562676b6251e8347f4b89907ace3/lib/fuse.c#L1483-L1486
    # That particular location seems to have been fixed in 2.8.0 and 2.7.0, but not in 2.6.5.
    # It seems to have been fixed only by accident in feature commit:
    # https://github.com/libfuse/libfuse/commit/3a7c00ec0c156123c47b53ec1cd7ead001fa4dfb
    def getattr(self, path, fh=None):
        '''
        Returns a dictionary with keys identical to the stat C structure of
        stat(2).

        st_atime, st_mtime and st_ctime should be floats.

        NOTE: There is an incompatibility between Linux and Mac OS X
        concerning st_nlink of directories. Mac OS X counts all files inside
        the directory, while Linux counts only the subdirectories.
        '''

        if path != '/':
            raise FuseOSError(errno.ENOENT)
        return dict(st_mode=(S_IFDIR | 0o755), st_nlink=2)

    @_nullable_dummy_function
    def getxattr(self, path, name, position=0):
        raise FuseOSError(ENOTSUP)

    @_nullable_dummy_function
    def init(self, path):
        '''
        Called on filesystem initialization. (Path is always /)

        Use it instead of __init__ if you start threads on initialization.
        '''

    @_nullable_dummy_function
    def ioctl(self, path, cmd, arg, fh, flags, data):
        raise FuseOSError(errno.ENOTTY)

    @_nullable_dummy_function
    def link(self, target, source):
        'creates a hard link `target -> source` (e.g. ln source target)'

        raise FuseOSError(errno.EROFS)

    @_nullable_dummy_function
    def listxattr(self, path):
        return []

    @_nullable_dummy_function
    def lock(self, path, fh, cmd, lock):
        raise FuseOSError(errno.ENOSYS)

    @_nullable_dummy_function
    def mkdir(self, path, mode):
        raise FuseOSError(errno.EROFS)

    @_nullable_dummy_function
    def mknod(self, path, mode, dev):
        raise FuseOSError(errno.EROFS)

    @_nullable_dummy_function
    def open(self, path, flags):
        '''
        When raw_fi is False (default case), open should return a numerical
        file handle.

        When raw_fi is True the signature of open becomes:
            open(self, path, fi)

        and the file handle should be set directly.
        '''

        return 0

    @_nullable_dummy_function
    def opendir(self, path):
        'Returns a numerical file handle.'

        return 0

    @_nullable_dummy_function
    def read(self, path, size, offset, fh):
        'Returns a string containing the data requested.'

        raise FuseOSError(errno.EIO)

    @_nullable_dummy_function
    def readdir(self, path, fh):
        '''
        Can return either a list of names, or a list of (name, attrs, offset)
        tuples. attrs is a dict as in getattr.
        '''

        return ['.', '..']

    @_nullable_dummy_function
    def readlink(self, path):
        raise FuseOSError(errno.ENOENT)

    @_nullable_dummy_function
    def release(self, path, fh):
        return 0

    @_nullable_dummy_function
    def releasedir(self, path, fh):
        return 0

    @_nullable_dummy_function
    def removexattr(self, path, name):
        raise FuseOSError(ENOTSUP)

    @_nullable_dummy_function
    def rename(self, old, new):
        raise FuseOSError(errno.EROFS)

    @_nullable_dummy_function
    def rmdir(self, path):
        raise FuseOSError(errno.EROFS)

    @_nullable_dummy_function
    def setxattr(self, path, name, value, options, position=0):
        raise FuseOSError(ENOTSUP)

    @_nullable_dummy_function
    def statfs(self, path):
        '''
        Returns a dictionary with keys identical to the statvfs C structure of
        statvfs(3).

        On Mac OS X f_bsize and f_frsize must be a power of 2
        (minimum 512).
        '''

        return {}

    @_nullable_dummy_function
    def symlink(self, target, source):
        'creates a symlink `target -> source` (e.g. ln -s source target)'

        raise FuseOSError(errno.EROFS)

    @_nullable_dummy_function
    def truncate(self, path, length, fh=None):
        raise FuseOSError(errno.EROFS)

    @_nullable_dummy_function
    def unlink(self, path):
        raise FuseOSError(errno.EROFS)

    @_nullable_dummy_function
    def utimens(self, path, times=None):
        'Times is a (atime, mtime) tuple. If None use current time.'

        return 0

    @_nullable_dummy_function
    def write(self, path, data, offset, fh):
        raise FuseOSError(errno.EROFS)

    @_nullable_dummy_function
    def poll(self, path, fh, ph, reventsp):
        raise FuseOSError(errno.ENOSYS)

    @_nullable_dummy_function
    def write_buf(self, path, buf, offset, fh):
        raise FuseOSError(errno.ENOSYS)

    @_nullable_dummy_function
    def read_buf(self, path, bufpp, size, offset, fh):
        raise FuseOSError(errno.ENOSYS)

    @_nullable_dummy_function
    def flock(self, path, fh, op):
        raise FuseOSError(errno.ENOSYS)

    @_nullable_dummy_function
    def fallocate(self, path, mode, offset, size, fh):
        raise FuseOSError(errno.ENOSYS)


class LoggingMixIn:
    log = logging.getLogger('fuse.log-mixin')

    def __call__(self, op, path, *args):
        self.log.debug('-> %s %s %s', op, path, repr(args))
        ret = '[Unhandled Exception]'
        try:
            ret = getattr(self, op)(path, *args)
            return ret
        except OSError as e:
            ret = str(e)
            raise
        finally:
            self.log.debug('<- %s %s', op, repr(ret))
