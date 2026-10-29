namespace Jarvis.WindowsBroker;

public static class Program
{
    public static async Task<int> Main(string[] args)
    {
        if (!OperatingSystem.IsWindows())
        {
            Console.Error.WriteLine("Jarvis Windows broker requires Windows.");
            return 2;
        }

        bool once = false;
        string? pipeName = null;
        string? keyPath = null;
        for (int index = 0; index < args.Length; index++)
        {
            if (args[index] == "--once")
            {
                once = true;
            }
            else if (args[index] == "--pipe-name" && index + 1 < args.Length)
            {
                pipeName = args[++index];
            }
            else if (args[index] == "--key-path" && index + 1 < args.Length)
            {
                keyPath = args[++index];
            }
            else
            {
                Console.Error.WriteLine(
                    "Usage: Jarvis.WindowsBroker [--once] [--pipe-name NAME] " +
                    "[--key-path PATH]");
                return 2;
            }
        }

        using CancellationTokenSource shutdown = new();
        Console.CancelKeyPress += (_, eventArgs) =>
        {
            eventArgs.Cancel = true;
            shutdown.Cancel();
        };

        BrokerGrantAuthority? authority = keyPath is null
            ? null
            : new BrokerGrantAuthority(BrokerKeyStore.LoadOrCreate(keyPath));
        BrokerServer server = new(pipeName, authority);
        Console.WriteLine($"Jarvis Windows broker {BrokerServer.Version}");
        Console.WriteLine($"Pipe: {server.PipeName}");
        Console.WriteLine("Execution: disabled");
        try
        {
            do
            {
                await server.HandleOneClientAsync(shutdown.Token).ConfigureAwait(false);
            }
            while (!once && !shutdown.IsCancellationRequested);
        }
        catch (OperationCanceledException) when (shutdown.IsCancellationRequested)
        {
            return 0;
        }

        return 0;
    }
}
