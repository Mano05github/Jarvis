using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

namespace Jarvis.WindowsBroker;

public static class BrokerKeyStore
{
    private const int KeyBytes = 32;
    private static readonly byte[] Entropy = Encoding.UTF8.GetBytes(
        "Jarvis.WindowsBroker/capability-key/v1");

    public static byte[] LoadOrCreateDefault()
    {
        string localData = Environment.GetFolderPath(
            Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(localData))
        {
            throw new InvalidOperationException("local_app_data_unavailable");
        }

        return LoadOrCreate(Path.Combine(
            localData,
            "Jarvis",
            "broker",
            "v1",
            "capability-key.dpapi"));
    }

    public static byte[] LoadOrCreate(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        string fullPath = Path.GetFullPath(path);
        string directory = Path.GetDirectoryName(fullPath)
            ?? throw new ArgumentException("key_path_has_no_directory", nameof(path));
        Directory.CreateDirectory(directory);
        if ((File.GetAttributes(directory) & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidOperationException("key_directory_reparse_point_denied");
        }

        if (File.Exists(fullPath))
        {
            return ReadKey(fullPath);
        }

        byte[] key = RandomNumberGenerator.GetBytes(KeyBytes);
        byte[] protectedKey = Dpapi.Protect(key, Entropy);
        string temporary = fullPath + $".{Guid.NewGuid():N}.tmp";
        try
        {
            using (FileStream stream = new(
                temporary,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                4096,
                FileOptions.WriteThrough))
            {
                stream.Write(protectedKey);
                stream.Flush(flushToDisk: true);
            }

            try
            {
                File.Move(temporary, fullPath);
            }
            catch (IOException) when (File.Exists(fullPath))
            {
                File.Delete(temporary);
                CryptographicOperations.ZeroMemory(key);
                return ReadKey(fullPath);
            }

            return key;
        }
        catch
        {
            if (File.Exists(temporary))
            {
                File.Delete(temporary);
            }

            CryptographicOperations.ZeroMemory(key);
            throw;
        }
    }

    private static byte[] ReadKey(string path)
    {
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidOperationException("key_file_reparse_point_denied");
        }

        byte[] protectedKey = File.ReadAllBytes(path);
        if (protectedKey.Length is < 32 or > 4096)
        {
            throw new InvalidOperationException("protected_key_size_invalid");
        }

        byte[] key = Dpapi.Unprotect(protectedKey, Entropy);
        if (key.Length != KeyBytes)
        {
            CryptographicOperations.ZeroMemory(key);
            throw new InvalidOperationException("grant_key_size_invalid");
        }

        return key;
    }
}

internal static class Dpapi
{
    private const int CryptprotectUiForbidden = 0x1;

    public static byte[] Protect(byte[] plaintext, byte[] entropy)
    {
        return Transform(plaintext, entropy, protect: true);
    }

    public static byte[] Unprotect(byte[] ciphertext, byte[] entropy)
    {
        return Transform(ciphertext, entropy, protect: false);
    }

    private static byte[] Transform(byte[] input, byte[] entropy, bool protect)
    {
        GCHandle inputHandle = GCHandle.Alloc(input, GCHandleType.Pinned);
        GCHandle entropyHandle = GCHandle.Alloc(entropy, GCHandleType.Pinned);
        DataBlob inputBlob = new(input.Length, inputHandle.AddrOfPinnedObject());
        DataBlob entropyBlob = new(entropy.Length, entropyHandle.AddrOfPinnedObject());
        DataBlob outputBlob = default;
        IntPtr description = IntPtr.Zero;
        try
        {
            bool succeeded = protect
                ? CryptProtectData(
                    ref inputBlob,
                    null,
                    ref entropyBlob,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    CryptprotectUiForbidden,
                    out outputBlob)
                : CryptUnprotectData(
                    ref inputBlob,
                    out description,
                    ref entropyBlob,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    CryptprotectUiForbidden,
                    out outputBlob);
            if (!succeeded)
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }

            byte[] output = new byte[outputBlob.Length];
            Marshal.Copy(outputBlob.Data, output, 0, output.Length);
            return output;
        }
        finally
        {
            inputHandle.Free();
            entropyHandle.Free();
            if (outputBlob.Data != IntPtr.Zero)
            {
                LocalFree(outputBlob.Data);
            }

            if (description != IntPtr.Zero)
            {
                LocalFree(description);
            }
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private readonly struct DataBlob
    {
        public DataBlob(int length, IntPtr data)
        {
            Length = length;
            Data = data;
        }

        public int Length { get; }

        public IntPtr Data { get; }
    }

    [DllImport("Crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptProtectData(
        ref DataBlob dataIn,
        string? description,
        ref DataBlob optionalEntropy,
        IntPtr reserved,
        IntPtr promptStruct,
        int flags,
        out DataBlob dataOut);

    [DllImport("Crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptUnprotectData(
        ref DataBlob dataIn,
        out IntPtr description,
        ref DataBlob optionalEntropy,
        IntPtr reserved,
        IntPtr promptStruct,
        int flags,
        out DataBlob dataOut);

    [DllImport("Kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr memory);
}
