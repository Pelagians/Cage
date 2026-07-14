using System;
using System.IO;
using System.Reflection;
using System.Text;

internal static class CageAssemblyInventory
{
    private static string Hex(byte[] bytes)
    {
        if (bytes == null || bytes.Length == 0)
        {
            return string.Empty;
        }

        StringBuilder builder = new StringBuilder(bytes.Length * 2);
        foreach (byte value in bytes)
        {
            builder.Append(value.ToString("x2"));
        }
        return builder.ToString();
    }

    public static int Main(string[] args)
    {
        if (args.Length != 2)
        {
            return 64;
        }

        string root = Path.GetFullPath(args[0]);
        using (StreamWriter writer = new StreamWriter(args[1], false, new UTF8Encoding(false)))
        {
            foreach (string file in Directory.GetFiles(root, "*.dll", SearchOption.AllDirectories))
            {
                try
                {
                    AssemblyName assembly = AssemblyName.GetAssemblyName(file);
                    string relative = file.Substring(root.Length)
                        .TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                        .Replace('\\', '/');
                    writer.Write(relative);
                    writer.Write('\t');
                    writer.Write(assembly.Name);
                    writer.Write('\t');
                    writer.Write(assembly.Version == null ? string.Empty : assembly.Version.ToString());
                    writer.Write('\t');
                    writer.WriteLine(Hex(assembly.GetPublicKeyToken()));
                }
                catch (BadImageFormatException)
                {
                }
                catch (FileLoadException)
                {
                }
            }
        }
        return 0;
    }
}
