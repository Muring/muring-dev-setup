using System;
using System.Diagnostics;
using System.IO;

internal static class Launcher
{
    [STAThread]
    private static int Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        try
        {
            var start = new ProcessStartInfo
            {
                FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), @"WindowsPowerShell\v1.0\powershell.exe"),
                Arguments = "-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File \"" + Path.Combine(root, "launch.ps1") + "\"",
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            using (var child = Process.Start(start))
            {
                child.WaitForExit();
                return child.ExitCode;
            }
        }
        catch (Exception error)
        {
            File.AppendAllText(Path.Combine(root, "controller.log"), error.ToString() + Environment.NewLine);
            return 1;
        }
    }
}
