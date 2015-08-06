This is the vdb package including vtrace from Kenshoto.  The origional website has vanished and several people in the community have there own source tree's with patches.  I've created this project to make this useful codebase available to everyone and support adding new features and patches.

The old linke is: http://www.kenshoto.com/vtrace/releases/

# vtrace #

vtrace is a cross-platform debugging api written in python.  Each supported platform has it's own support module.

| OS | Debug Method |
|:---|:-------------|
| Windows | System Debugging API |
| Darwin | ptrace       |
| Linux | ptrace and /proc |
| FreeBSD | ptrace and libkvm |
| Solaris | ptrace       |

## Avoiding PT\_DENY\_ATTACH Process Flag ##

A simple anti-debugging trick used by many processes on OS X involves calling ptrace with the PT\_DENY\_ATTACH flag.  This is easy to get around using a kernel module that hooks ptrace and ignores the flag.  You can download a working kext from here: [Fixing ptrace](http://landonf.bikemonkey.org/code/macosx/Leopard_PT_DENY_ATTACH.20080122.html).

# From the old readme #

## Intro ##

VDB is a debugger written using the vtrace API.  For the list
of kewl stuff and supported features, see the vtrace docs.


## Usage ##

I usually run it directly from the checkout without going through
any kind of installation.  From a windows/unix command prompt,
"python vdbbin" should suffice.

If you want to use the gui (on mac/linux/windows) you will need
a working install of pygtk (which means gtk/pango/etc).

I'm not really one for writting a LOT of docs, but explore and have fun.


## Known Iusses ##

  * -R and firewalls
> > Remove debugging with vdb is possible with the use of the
> > "server" command and the -R option.  **However**, cobra
> > (the underlying RMI model) will attempt transparent reconnection
> > for robustness.  This means that firewalls can cause it to hang
> > as it tries to reconnect.  This also means that one socket dying
> > once doesn't destroy your debugging session ;)

  * NonBlocking or ThreadWrap modes
> > Though these modes are listed in the modes selection interface
> > you may **not** turn them off.  They are critical to the function
> > of vdb as a non-blocking debugger...

## PT\_WRITE\_U error on Linux ##

The USER\_i386 Structure in vtrace/platforms/linux.py is hardcoded and
it changes depending on the kernel version. It needs to match the
struct user which is used by the kernel and defined in
/usr/include/sys/user.h, so the sizes are wrong and that's why you get
the PT\_WRITE\_U error. You need to modify the linux.py file to exactly
match the struct your kernel is using (mainly the size).

For instance, in my case that file contains (among other things, this
is only the interesting part):

```

/* These are the 32-bit x86 structures.  */
struct user_fpxregs_struct
{
  unsigned short int cwd;
  unsigned short int swd;
  unsigned short int twd;
  unsigned short int fop;
  long int fip;
  long int fcs;
  long int foo;
  long int fos;
  long int mxcsr;
  long int reserved;
  long int st_space[32];   /* 8*16 bytes for each FP-reg = 128 bytes */
  long int xmm_space[32];  /* 8*16 bytes for each XMM-reg = 128 bytes */
  long int padding[56];
};

struct user_regs_struct
{
  long int ebx;
  long int ecx;
  long int edx;
  long int esi;
  long int edi;
  long int ebp;
  long int eax;
  long int xds;
  long int xes;
  long int xfs;
  long int xgs;
  long int orig_eax;
  long int eip;
  long int xcs;
  long int eflags;
  long int esp;
  long int xss;
};

struct user
{
  struct user_regs_struct       regs;
  int                           u_fpvalid;
  struct user_fpregs_struct     i387;
  unsigned long int             u_tsize;
  unsigned long int             u_dsize;
  unsigned long int             u_ssize;
  unsigned long                 start_code;
  unsigned long                 start_stack;
  long int                      signal;
  int                           reserved;
  struct user_regs_struct*      u_ar0;
  struct user_fpregs_struct*    u_fpstate;
  unsigned long int             magic;
  char                          u_comm [32];
  int                           u_debugreg [8];
};
```

So I modified vtrace/platforms/linux.py to contain (interesting parts
only, again):

```
class user_regs_i386(Structure):
    _fields_ = (
        ("ebx",  c_ulong),
        ("ecx",  c_ulong),
        ("edx",  c_ulong),
        ("esi",  c_ulong),
        ("edi",  c_ulong),
        ("ebp",  c_ulong),
        ("eax",  c_ulong),
        ("ds",   c_ushort),
        ("__ds", c_ushort),
        ("es",   c_ushort),
        ("__es", c_ushort),
        ("fs",   c_ushort),
        ("__fs", c_ushort),
        ("gs",   c_ushort),
        ("__gs", c_ushort),
        ("orig_eax", c_ulong),
        ("eip",  c_ulong),
        ("cs",   c_ushort),
        ("__cs", c_ushort),
        ("eflags", c_ulong),
        ("esp",  c_ulong),
        ("ss",   c_ushort),
        ("__ss", c_ushort),
    )

class user_fpxregs(Structure):
  _fields_ = (
    ("cwd", c_ushort),
    ("swd", c_ushort),
    ("twd", c_ushort),
    ("fop", c_ushort),
    ("fip", c_long),
    ("fcs", c_long),
    ("foo", c_long),
    ("fos", c_long),
    ("mxcsr", c_long),
    ("reserved", c_long),
    ("st_space", c_long * 32),
    ("xmm_space", c_long * 32),
    ("padding", c_long * 56),
      )

class USER_i386(Structure):
    _fields_ = (
        # NOTE: Expand out the user regs struct so
        #       we can make one call to _rctx_Import
        ("regs",       user_regs_i386),
        ("u_fpvalid",  c_ulong),
        ("i387",       user_fpxregs),
        ("u_tsize",    c_ulong),
        ("u_dsize",    c_ulong),
        ("u_ssize",    c_ulong),
        ("start_code", c_ulong),
        ("start_stack",c_ulong),
        ("signal",     c_ulong),
        ("reserved",   c_ulong),
        ("u_ar0",      c_void_p),
        ("u_fpstate",  c_void_p),
        ("magic",      c_ulong),
        ("u_comm",     c_char*32),
        ("debug0",     c_ulong),
        ("debug1",     c_ulong),
        ("debug2",     c_ulong),
        ("debug3",     c_ulong),
        ("debug4",     c_ulong),
        ("debug5",     c_ulong),
        ("debug6",     c_ulong),
        ("debug7",     c_ulong),
    )
```