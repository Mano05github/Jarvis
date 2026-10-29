using System.Buffers.Binary;
using System.IO.Pipes;
using System.Security.Principal;
using System.Security.Cryptography;
using System.Text;
using Jarvis.WindowsBroker;

namespace Jarvis.WindowsBroker.ContractTests;

public static class Program
{
    private static int _checks;

    public static async Task<int> Main()
    {
        try
        {
            await ProtocolRoundTripAsync().ConfigureAwait(false);
            await ProtocolRejectsInvalidLengthsAsync().ConfigureAwait(false);
            await ProtocolRejectsTruncationAsync().ConfigureAwait(false);
            await ProtocolRejectsUnknownJsonAsync().ConfigureAwait(false);
            ValidateStrictRequestContract();
            CapabilityGrantContract();
            BrokerKeyStoreRoundTrip();
            await CurrentUserPipeIntegrationAsync().ConfigureAwait(false);
            Console.WriteLine($"Broker contract tests passed: {_checks}");
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine($"Broker contract test failed: {error.Message}");
            return 1;
        }
    }

    private static async Task ProtocolRoundTripAsync()
    {
        BrokerRequest expected = HealthRequest();
        await using MemoryStream stream = new();
        await BrokerProtocol.WriteAsync(stream, expected, CancellationToken.None)
            .ConfigureAwait(false);
        stream.Position = 0;
        BrokerRequest actual = await BrokerProtocol.ReadAsync<BrokerRequest>(
            stream,
            CancellationToken.None).ConfigureAwait(false);
        Check(actual == expected, "protocol round trip");
    }

    private static async Task ProtocolRejectsInvalidLengthsAsync()
    {
        foreach (int length in new[] { 0, -1, BrokerProtocol.MaximumMessageBytes + 1 })
        {
            byte[] prefix = new byte[sizeof(int)];
            BinaryPrimitives.WriteInt32LittleEndian(prefix, length);
            await using MemoryStream stream = new(prefix);
            await ExpectProtocolErrorAsync(
                "message_length_invalid",
                () => BrokerProtocol.ReadAsync<BrokerRequest>(stream, CancellationToken.None))
                .ConfigureAwait(false);
        }
    }

    private static async Task ProtocolRejectsTruncationAsync()
    {
        byte[] prefix = new byte[sizeof(int)];
        BinaryPrimitives.WriteInt32LittleEndian(prefix, 20);
        await using MemoryStream stream = new();
        await stream.WriteAsync(prefix).ConfigureAwait(false);
        await stream.WriteAsync(Encoding.UTF8.GetBytes("{}" )).ConfigureAwait(false);
        stream.Position = 0;
        await ExpectProtocolErrorAsync(
            "message_truncated",
            () => BrokerProtocol.ReadAsync<BrokerRequest>(stream, CancellationToken.None))
            .ConfigureAwait(false);
    }

    private static async Task ProtocolRejectsUnknownJsonAsync()
    {
        byte[] json = Encoding.UTF8.GetBytes(
            "{\"schema_version\":\"1.0\",\"request_id\":\"" +
            Guid.NewGuid() +
            "\",\"operation\":\"broker.health\",\"unexpected\":true}");
        byte[] prefix = new byte[sizeof(int)];
        BinaryPrimitives.WriteInt32LittleEndian(prefix, json.Length);
        await using MemoryStream stream = new();
        await stream.WriteAsync(prefix).ConfigureAwait(false);
        await stream.WriteAsync(json).ConfigureAwait(false);
        stream.Position = 0;
        await ExpectProtocolErrorAsync(
            "message_json_invalid",
            () => BrokerProtocol.ReadAsync<BrokerRequest>(stream, CancellationToken.None))
            .ConfigureAwait(false);
    }

    private static void ValidateStrictRequestContract()
    {
        HealthRequest().Validate();
        ExpectValidationError(
            "schema_version_unsupported",
            HealthRequest() with { SchemaVersion = "2.0" });
        ExpectValidationError(
            "request_id_invalid",
            HealthRequest() with { RequestId = Guid.Empty });
        ExpectValidationError(
            "operation_not_registered",
            HealthRequest() with { Operation = "shell.run" });
        ExpectValidationError(
            "health_arguments_forbidden",
            HealthRequest() with { ApplicationId = "notepad" });
        ExpectValidationError(
            "application_id_required",
            HealthRequest() with { Operation = "windows.application.open" });
        ExpectValidationError(
            "capability_required",
            HealthRequest() with
            {
                Operation = "windows.application.open",
                ApplicationId = "notepad",
            });
        ExpectValidationError(
            "application_id_invalid",
            HealthRequest() with
            {
                Operation = "windows.application.open",
                ApplicationId = "..\\cmd.exe",
            });
    }

    private static void CapabilityGrantContract()
    {
        DateTimeOffset now = new(2026, 10, 18, 12, 0, 0, TimeSpan.Zero);
        BrokerGrantAuthority authority = new(
            Enumerable.Repeat((byte)0x5a, 32).ToArray(),
            () => now);
        BrokerCapabilityGrant grant = authority.Issue(
            Guid.NewGuid(),
            Guid.NewGuid(),
            Guid.NewGuid(),
            "windows.application.open",
            "notepad",
            new string('a', 64));

        authority.Validate(grant, "windows.application.open", "notepad");
        Check(true, "valid capability accepted");
        ExpectAuthorizationError(
            "capability_action_mismatch",
            () => authority.Validate(grant, "windows.application.close", "notepad"));
        ExpectAuthorizationError(
            "capability_resource_mismatch",
            () => authority.Validate(grant, "windows.application.open", "calculator"));
        ExpectAuthorizationError(
            "capability_authenticator_mismatch",
            () => authority.Validate(
                grant with { PayloadDigest = new string('b', 64) },
                "windows.application.open",
                "notepad"));

        authority.Consume(grant, "windows.application.open", "notepad");
        Check(true, "capability consumed atomically");
        ExpectAuthorizationError(
            "capability_replayed",
            () => authority.Consume(grant, "windows.application.open", "notepad"));

        now = grant.ExpiresAt;
        ExpectAuthorizationError(
            "capability_expired",
            () => authority.Validate(grant, "windows.application.open", "notepad"));
    }

    private static void BrokerKeyStoreRoundTrip()
    {
        string directory = Path.Combine(
            Environment.CurrentDirectory,
            "storage",
            "temp",
            $"broker-key-test-{Guid.NewGuid():N}");
        string path = Path.Combine(directory, "key.dpapi");
        try
        {
            byte[] first = BrokerKeyStore.LoadOrCreate(path);
            byte[] second = BrokerKeyStore.LoadOrCreate(path);
            Check(first.Length == 32, "broker key length");
            Check(
                CryptographicOperations.FixedTimeEquals(first, second),
                "DPAPI key persistence");
            Check(
                !File.ReadAllBytes(path).AsSpan().SequenceEqual(first),
                "broker key encrypted at rest");
            CryptographicOperations.ZeroMemory(first);
            CryptographicOperations.ZeroMemory(second);
        }
        finally
        {
            if (Directory.Exists(directory))
            {
                Directory.Delete(directory, recursive: true);
            }
        }
    }

    private static async Task CurrentUserPipeIntegrationAsync()
    {
        string pipeName = $"jarvis-broker-test-{Guid.NewGuid():N}";
        BrokerGrantAuthority authority = new(RandomNumberGenerator.GetBytes(32));
        BrokerServer server = new(pipeName, authority);
        using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(10));
        Task serverTask = server.HandleOneClientAsync(timeout.Token);
        await using NamedPipeClientStream client = new(
            ".",
            pipeName,
            PipeDirection.InOut,
            PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly,
            TokenImpersonationLevel.Identification);
        await client.ConnectAsync(timeout.Token).ConfigureAwait(false);
        BrokerRequest request = HealthRequest();
        await BrokerProtocol.WriteAsync(client, request, timeout.Token).ConfigureAwait(false);
        BrokerResponse response = await BrokerProtocol.ReadAsync<BrokerResponse>(
            client,
            timeout.Token).ConfigureAwait(false);
        await serverTask.ConfigureAwait(false);
        Check(
            response.RequestId == request.RequestId,
            $"response request binding ({response.Status}/{response.Code}/{response.RequestId})");
        Check(response.Status == "ok", "health status");
        Check(response.Code == "broker_ready_execution_disabled", "execution disabled");
        Check(response.CallerSid == BrokerIdentity.CurrentUserSid(), "caller SID binding");

        pipeName = $"jarvis-broker-test-{Guid.NewGuid():N}";
        server = new BrokerServer(pipeName, authority);
        serverTask = server.HandleOneClientAsync(timeout.Token);
        await using NamedPipeClientStream actionClient = new(
            ".",
            pipeName,
            PipeDirection.InOut,
            PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly,
            TokenImpersonationLevel.Identification);
        await actionClient.ConnectAsync(timeout.Token).ConfigureAwait(false);
        BrokerRequest action = HealthRequest() with
        {
            Operation = "windows.application.open",
            ApplicationId = "notepad",
            CapabilityGrant = authority.Issue(
                Guid.NewGuid(),
                Guid.NewGuid(),
                Guid.NewGuid(),
                "windows.application.open",
                "notepad",
                new string('c', 64)),
        };
        await BrokerProtocol.WriteAsync(actionClient, action, timeout.Token)
            .ConfigureAwait(false);
        response = await BrokerProtocol.ReadAsync<BrokerResponse>(actionClient, timeout.Token)
            .ConfigureAwait(false);
        await serverTask.ConfigureAwait(false);
        Check(response.Status == "denied", "action denied before executor certification");
        Check(response.Code == "execution_disabled", "fail-closed action code");
    }

    private static BrokerRequest HealthRequest()
    {
        return new BrokerRequest
        {
            SchemaVersion = BrokerProtocol.SchemaVersion,
            RequestId = Guid.NewGuid(),
            Operation = "broker.health",
        };
    }

    private static async Task ExpectProtocolErrorAsync(
        string code,
        Func<Task<BrokerRequest>> action)
    {
        try
        {
            await action().ConfigureAwait(false);
            throw new InvalidOperationException($"Expected protocol error: {code}");
        }
        catch (BrokerProtocolException error) when (error.Code == code)
        {
            _checks++;
        }
    }

    private static void ExpectValidationError(string code, BrokerRequest request)
    {
        try
        {
            request.Validate();
            throw new InvalidOperationException($"Expected validation error: {code}");
        }
        catch (BrokerProtocolException error) when (error.Code == code)
        {
            _checks++;
        }
    }

    private static void ExpectAuthorizationError(string code, Action action)
    {
        try
        {
            action();
            throw new InvalidOperationException($"Expected authorization error: {code}");
        }
        catch (BrokerAuthorizationException error) when (error.Code == code)
        {
            _checks++;
        }
    }

    private static void Check(bool condition, string name)
    {
        if (!condition)
        {
            throw new InvalidOperationException($"Check failed: {name}");
        }

        _checks++;
    }
}
