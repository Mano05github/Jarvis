using System.Buffers.Binary;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Jarvis.WindowsBroker;

public static class BrokerProtocol
{
    public const string SchemaVersion = "1.0";
    public const int MaximumMessageBytes = 64 * 1024;

    public static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = false,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        WriteIndented = false,
    };

    public static async Task<T> ReadAsync<T>(Stream stream, CancellationToken cancellationToken)
    {
        byte[] prefix = new byte[sizeof(int)];
        await ReadExactlyAsync(stream, prefix, cancellationToken).ConfigureAwait(false);
        int length = BinaryPrimitives.ReadInt32LittleEndian(prefix);
        if (length <= 0 || length > MaximumMessageBytes)
        {
            throw new BrokerProtocolException("message_length_invalid");
        }

        byte[] payload = new byte[length];
        await ReadExactlyAsync(stream, payload, cancellationToken).ConfigureAwait(false);
        try
        {
            return JsonSerializer.Deserialize<T>(payload, JsonOptions)
                ?? throw new BrokerProtocolException("message_json_null");
        }
        catch (JsonException error)
        {
            throw new BrokerProtocolException("message_json_invalid", error);
        }
    }

    public static async Task WriteAsync<T>(
        Stream stream,
        T message,
        CancellationToken cancellationToken)
    {
        byte[] payload = JsonSerializer.SerializeToUtf8Bytes(message, JsonOptions);
        if (payload.Length <= 0 || payload.Length > MaximumMessageBytes)
        {
            throw new BrokerProtocolException("message_length_invalid");
        }

        byte[] prefix = new byte[sizeof(int)];
        BinaryPrimitives.WriteInt32LittleEndian(prefix, payload.Length);
        await stream.WriteAsync(prefix, cancellationToken).ConfigureAwait(false);
        await stream.WriteAsync(payload, cancellationToken).ConfigureAwait(false);
        await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
    }

    private static async Task ReadExactlyAsync(
        Stream stream,
        Memory<byte> buffer,
        CancellationToken cancellationToken)
    {
        int offset = 0;
        while (offset < buffer.Length)
        {
            int count = await stream.ReadAsync(buffer[offset..], cancellationToken)
                .ConfigureAwait(false);
            if (count == 0)
            {
                throw new BrokerProtocolException("message_truncated");
            }

            offset += count;
        }
    }
}

public sealed class BrokerProtocolException : Exception
{
    public BrokerProtocolException(string code, Exception? innerException = null)
        : base(code, innerException)
    {
        Code = code;
    }

    public string Code { get; }
}

public sealed record BrokerRequest
{
    public required string SchemaVersion { get; init; }

    public required Guid RequestId { get; init; }

    public required string Operation { get; init; }

    public string? ApplicationId { get; init; }

    public BrokerCapabilityGrant? CapabilityGrant { get; init; }

    public void Validate()
    {
        if (SchemaVersion != BrokerProtocol.SchemaVersion)
        {
            throw new BrokerProtocolException("schema_version_unsupported");
        }

        if (RequestId == Guid.Empty)
        {
            throw new BrokerProtocolException("request_id_invalid");
        }

        if (Operation is not (
            "broker.health" or
            "windows.application.open" or
            "windows.application.close"))
        {
            throw new BrokerProtocolException("operation_not_registered");
        }

        bool isHealth = Operation == "broker.health";
        if (isHealth && (ApplicationId is not null || CapabilityGrant is not null))
        {
            throw new BrokerProtocolException("health_arguments_forbidden");
        }

        if (!isHealth && string.IsNullOrWhiteSpace(ApplicationId))
        {
            throw new BrokerProtocolException("application_id_required");
        }

        if (ApplicationId is not null && !IsCanonicalApplicationId(ApplicationId))
        {
            throw new BrokerProtocolException("application_id_invalid");
        }

        if (!isHealth && CapabilityGrant is null)
        {
            throw new BrokerProtocolException("capability_required");
        }
    }

    private static bool IsCanonicalApplicationId(string value)
    {
        if (value.Length is < 1 or > 64 || !char.IsAsciiLetterOrDigit(value[0]))
        {
            return false;
        }

        return value.All(character =>
            char.IsAsciiLetterOrDigit(character) || character == '-');
    }
}

public sealed record BrokerResponse
{
    public required string SchemaVersion { get; init; }

    public required Guid RequestId { get; init; }

    public required string Status { get; init; }

    public required string Code { get; init; }

    public required string BrokerVersion { get; init; }

    public string? CallerSid { get; init; }
}
