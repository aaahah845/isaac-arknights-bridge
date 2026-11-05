using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

static class Entry {
    [STAThread]
    static int Main() {
        try {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string python = Path.Combine(root, "runtime", "pythonw.exe");
            if (!File.Exists(python)) throw new Exception("请先完整解压安装包，再打开此程序。");
            string mode = "start";
            string script = Path.Combine(root, "setup", mode == "start" ? "start.py" : "wizard.py");
            var info = new ProcessStartInfo(python, Quote(script) + " " + mode);
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.WindowStyle = ProcessWindowStyle.Hidden;
            Process.Start(info);
            return 0;
        } catch (Exception error) {
            MessageBox.Show(error.Message, "以撒 × 明日方舟", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
    static string Quote(string text) {
        return "\"" + text.Replace("\"", "\\\"") + "\"";
    }
}
