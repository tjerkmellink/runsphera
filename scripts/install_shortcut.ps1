<#
Create a RunSphera.lnk shortcut that pins to the taskbar with the RunSphera
icon (not the Python feather).

Two things make pinning work:
  1. The shortcut's IconLocation points at running_coach/assets/RunSphera.ico.
  2. The shortcut carries System.AppUserModel.ID = "RunSphera.Coach", matching
     the SetCurrentProcessExplicitAppUserModelID the app sets at launch. That
     shared identity is what lets Windows merge the running window into the
     pinned shortcut instead of falling back to pythonw.exe's icon.

Run once after setup:
    pwsh -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1

Creates the shortcut in the repo root and on the Desktop. Right-click either
one -> "Pin to taskbar" (or just pin the running window once launched from it).
#>

$ErrorActionPreference = 'Stop'

$Root    = Split-Path -Parent $PSScriptRoot
$PythonW = Join-Path $Root '.venv\Scripts\pythonw.exe'
$Icon    = Join-Path $Root 'running_coach\assets\RunSphera.ico'
$AppId   = 'RunSphera.Coach'
$Arguments = '-m running_coach.desktop'

if (-not (Test-Path $PythonW)) { throw "pythonw.exe not found at $PythonW - run install.cmd first to create the venv." }
if (-not (Test-Path $Icon))    { throw "Icon not found at $Icon - run scripts\build_brand_assets.py first." }

Add-Type -Language CSharp @'
using System;
using System.Runtime.InteropServices;

namespace RunSphera {
    [StructLayout(LayoutKind.Sequential)]
    public struct PROPERTYKEY { public Guid fmtid; public uint pid; }

    [StructLayout(LayoutKind.Sequential)]
    public struct PROPVARIANT { public ushort vt; ushort r1, r2, r3; public IntPtr p; public IntPtr p2; }

    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IShellLinkW {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder f, int cch, IntPtr pfd, uint fl);
        void GetIDList(out IntPtr ppidl);
        void SetIDList(IntPtr pidl);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder n, int cch);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string n);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder d, int cch);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string d);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder a, int cch);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string a);
        void GetHotkey(out short w);
        void SetHotkey(short w);
        void GetShowCmd(out int c);
        void SetShowCmd(int c);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder i, int cch, out int idx);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string i, int idx);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string r, uint res);
        void Resolve(IntPtr hwnd, uint fl);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string p);
    }

    [ComImport, Guid("0000010b-0000-0000-C000-000000000046"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IPersistFile {
        void GetClassID(out Guid pClassID);
        [PreserveSig] int IsDirty();
        void Load([MarshalAs(UnmanagedType.LPWStr)] string f, uint mode);
        void Save([MarshalAs(UnmanagedType.LPWStr)] string f, [MarshalAs(UnmanagedType.Bool)] bool remember);
        void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string f);
        void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string f);
    }

    [ComImport, Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IPropertyStore {
        void GetCount(out uint c);
        void GetAt(uint i, out PROPERTYKEY key);
        void GetValue(ref PROPERTYKEY key, out PROPVARIANT pv);
        void SetValue(ref PROPERTYKEY key, ref PROPVARIANT pv);
        void Commit();
    }

    public static class ShortcutMaker {
        const ushort VT_LPWSTR = 31;

        public static void Create(string lnkPath, string target, string args, string workDir, string icon, string appId) {
            Type t = Type.GetTypeFromCLSID(new Guid("00021401-0000-0000-C000-000000000046")); // CLSID_ShellLink
            object obj = Activator.CreateInstance(t);
            IShellLinkW link = (IShellLinkW)obj;
            link.SetPath(target);
            link.SetArguments(args);
            link.SetWorkingDirectory(workDir);
            link.SetIconLocation(icon, 0);
            link.SetShowCmd(1); // SW_SHOWNORMAL

            // System.AppUserModel.ID  (PKEY_AppUserModel_ID: {9F4C2855-...}, pid 5)
            // Build a VT_LPWSTR PROPVARIANT by hand to avoid propsys.dll interop.
            IPropertyStore store = (IPropertyStore)obj;
            PROPERTYKEY key = new PROPERTYKEY {
                fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
            PROPVARIANT pv = new PROPVARIANT { vt = VT_LPWSTR, p = Marshal.StringToCoTaskMemUni(appId) };
            store.SetValue(ref key, ref pv);   // store copies the value...
            store.Commit();
            Marshal.FreeCoTaskMem(pv.p);       // ...so freeing our copy afterwards is safe

            IPersistFile file = (IPersistFile)obj;
            file.Save(lnkPath, true);
            Marshal.ReleaseComObject(obj);
        }
    }
}
'@

function New-RunSpheraShortcut([string]$Path) {
    [RunSphera.ShortcutMaker]::Create($Path, $PythonW, $Arguments, $Root, $Icon, $AppId)
    Write-Host "  created $Path"
}

Write-Host "Creating RunSphera shortcuts (icon + AppUserModelID '$AppId')..."
$targets = @(
    (Join-Path $Root 'RunSphera.lnk'),                                        # repo root
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'RunSphera.lnk'),    # Desktop
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'RunSphera.lnk')    # Start Menu (searchable)
)
foreach ($t in $targets) { New-RunSpheraShortcut $t }
Write-Host "Done. Right-click the Desktop or Start-Menu shortcut -> 'Pin to taskbar'."
