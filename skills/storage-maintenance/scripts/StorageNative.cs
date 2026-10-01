using System;
using System.IO;
using System.Text;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Web.Script.Serialization;
using Microsoft.Win32.SafeHandles;

public static class StorageNative {
    [StructLayout(LayoutKind.Sequential)] public struct Info {
        public uint Attributes; public System.Runtime.InteropServices.ComTypes.FILETIME Created, Accessed, Written;
        public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }
    [StructLayout(LayoutKind.Sequential)] struct Disposition { [MarshalAs(UnmanagedType.Bool)] public bool Delete; }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern SafeFileHandle CreateFile(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetFileInformationByHandle(SafeFileHandle handle, out Info info);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern uint GetCompressedFileSizeW(string path, out uint high);
    [DllImport("kernel32.dll")] static extern void SetLastError(uint error);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern uint GetFinalPathNameByHandle(SafeFileHandle handle, StringBuilder path, uint size, uint flags);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetFileInformationByHandle(SafeFileHandle handle, int kind, ref Disposition info, uint size);
    static JavaScriptSerializer Json = new JavaScriptSerializer();
    static string[] Protected = {".git", ".hg", ".svn", ".codex", ".claude", ".ssh", ".aws", ".azure", "credentials", "credentials.json", "auth.json", "vm_bundles", "windows", "program files", "program files (x86)", "programdata", "winsxs", "installer", "pagefile.sys", "swapfile.sys", "hiberfil.sys"};
    public static bool IsProtected(string path) {
        string name = Path.GetFileName(path).ToLowerInvariant();
        foreach (string p in Protected) if (name == p) return true;
        if (name == ".env" || name.StartsWith(".env.")) return true;
        foreach (string suffix in new string[]{".vhd", ".vhdx", ".avhdx", ".vmdk", ".qcow2", ".pem", ".key"}) if (name.EndsWith(suffix)) return true;
        return false;
    }
    static SafeFileHandle Open(string path, bool deletion) {
        SafeFileHandle h = CreateFile(path, deletion ? 0x10080u : 0x80u, deletion ? 1u : 7u, IntPtr.Zero, 3, 0x02200000, IntPtr.Zero);
        if (h.IsInvalid) { h.Dispose(); throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()); }
        return h;
    }
    static Info Stat(SafeFileHandle h) {
        Info info; if (!GetFileInformationByHandle(h, out info)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        return info;
    }
    static void Ancestors(string path, bool cleanup) {
        string current = Path.GetFullPath(path);
        while (current != null) {
            if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0) throw new IOException("reparse_ancestor");
            if (cleanup && (IsProtected(current) || Directory.Exists(Path.Combine(current, ".git")) || File.Exists(Path.Combine(current, ".git"))))
                throw new IOException("protected_or_repository_ancestor");
            current = Path.GetDirectoryName(current.TrimEnd('\\'));
            if (current != null && current.EndsWith(":")) current += "\\";
        }
    }
    public static void Save(string path, object value) {
        if (String.IsNullOrEmpty(path)) return;
        File.WriteAllText(path + ".tmp", Json.Serialize(value), new UTF8Encoding(false));
        if (File.Exists(path)) File.Delete(path);
        File.Move(path + ".tmp", path);
    }
    public static Dictionary<string,object> Inspect(string path, int seconds, string progress, bool cleanup, bool execute, string expected, long expectedBytes) {
        var result = new Dictionary<string,object>();
        result["state"] = "partial"; result["path"] = path;
        long logical=0, allocated=0, count=0, duplicates=0, links=0, reparses=0, errors=0, deleted=0;
        bool allocationKnown=true; double modified=0;
        var rows = new List<string>(); var seen = new HashSet<string>();
        var handles = new List<SafeFileHandle>(); var locations = new List<string>();
        var stack = new Stack<string>(); var issues = new List<string>();
        var watch = Stopwatch.StartNew(); double last=0;
        Action checkpoint = delegate {
            result["observed_logical_bytes"]=logical; result["observed_allocated_bytes"]=allocated;
            result["logical_bytes"]=null; result["allocated_bytes"]=null;
            result["files"]=count; result["hardlinks"]=links; result["duplicate_links"]=duplicates;
            result["skipped_reparse"]=reparses; result["errors"]=errors; result["issues"]=issues.ToArray();
            result["modified_epoch"]=modified; Save(progress,result);
        };
        try {
            Ancestors(path,cleanup); stack.Push(Path.GetFullPath(path));
            while (stack.Count>0) {
                if (watch.Elapsed.TotalSeconds>seconds) { issues.Add("timeout"); errors++; break; }
                string current=stack.Pop(); SafeFileHandle h=null;
                try {
                    if (cleanup && IsProtected(current)) throw new IOException("protected_content");
                    h=Open(current,execute); Info info=Stat(h);
                    if ((info.Attributes & 0x400)!=0) { reparses++; if (cleanup) throw new IOException("reparse_point"); continue; }
                    var finalPath=new StringBuilder(32768);
                    uint length=GetFinalPathNameByHandle(h,finalPath,(uint)finalPath.Capacity,0);
                    if (length==0 || length>=finalPath.Capacity) throw new IOException("final_path_unknown");
                    string final=finalPath.ToString(); if (final.StartsWith("\\\\?\\")) final=final.Substring(4);
                    if (!String.Equals(final,Path.GetFullPath(current),StringComparison.OrdinalIgnoreCase)) throw new IOException("path_escape");
                    string id=info.Volume+":"+info.IndexHigh+":"+info.IndexLow;
                    ulong bytes=((ulong)info.SizeHigh<<32)|info.SizeLow;
                    long write=((long)info.Written.dwHighDateTime<<32)|(uint)info.Written.dwLowDateTime;
                    modified=Math.Max(modified,(DateTime.FromFileTimeUtc(write)-new DateTime(1970,1,1)).TotalSeconds);
                    rows.Add(current.Substring(Path.GetFullPath(path).Length)+"|"+id+"|"+info.Attributes+"|"+bytes+"|"+write+"|"+info.Links);
                    if (execute) { handles.Add(h); locations.Add(current); h=null; }
                    if ((info.Attributes & 0x10)!=0) {
                        foreach (string child in Directory.EnumerateFileSystemEntries(current)) stack.Push(child);
                    } else {
                        if (info.Links>1) links++;
                        if (seen.Add(id)) {
                            count++; logical+=(long)bytes;
                            SetLastError(0); uint high; uint low=GetCompressedFileSizeW(current,out high); int error=Marshal.GetLastWin32Error();
                            if (low==UInt32.MaxValue && error!=0) { allocationKnown=false; errors++; if (issues.Count<10) issues.Add("allocation_error:"+error); }
                            else allocated+=(long)(((ulong)high<<32)|low);
                        } else duplicates++;
                    }
                } catch (Exception e) {
                    errors++; if (issues.Count<10) issues.Add(e.GetType().Name+":"+e.Message);
                    if (execute) throw;
                } finally { if (h!=null) h.Dispose(); }
                if (watch.Elapsed.TotalSeconds-last>=1) { checkpoint(); last=watch.Elapsed.TotalSeconds; }
            }
            checkpoint(); rows.Sort(StringComparer.Ordinal);
            string fingerprint;
            using (var sha=SHA256.Create()) fingerprint=BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(String.Join("\n",rows)))).Replace("-","").ToLowerInvariant();
            result["fingerprint"]=fingerprint;
            if (errors==0 && reparses==0) {
                result["state"]="complete"; result["logical_bytes"]=logical;
                result["allocated_bytes"]=allocationKnown ? (object)allocated : null;
            }
            if (execute) {
                if (errors!=0 || reparses!=0 || links!=0 || fingerprint!=expected || logical!=expectedBytes)
                    throw new IOException("candidate_changed_or_incomplete");
                // All handles were acquired before the first mutation, without
                // sharing write/delete. Delete children first by handle, not path.
                for (int i=handles.Count-1;i>=0;i--) {
                    if (watch.Elapsed.TotalSeconds>seconds) throw new IOException("apply_timeout");
                    Disposition d=new Disposition();d.Delete=true;
                    if (!SetFileInformationByHandle(handles[i],4,ref d,(uint)Marshal.SizeOf(typeof(Disposition))))
                        throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                    handles[i].Dispose();
                    deleted++;
                }
                result["state"]="deleted";
            }
        } catch (Exception e) {
            result["state"]=execute ? "refused_or_partial" : "unknown";
            result["logical_bytes"]=null;result["allocated_bytes"]=null;
            result["error"]=e.GetType().Name+":"+e.Message;
        } finally { foreach (var h in handles) h.Dispose(); }
        result["deleted_entries"]=deleted; Save(progress,result); return result;
    }
}
