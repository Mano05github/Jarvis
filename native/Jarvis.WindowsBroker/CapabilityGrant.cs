using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Jarvis.WindowsBroker;

public sealed record BrokerCapabilityGrant
{
    public required string SchemaVersion { get; init; }

    public required Guid GrantId { get; init; }

    public required Guid SessionId { get; init; }

    public required Guid TaskId { get; init; }

    public required Guid ApprovalId { get; init; }

    public required string Action { get; init; }

    public required string ApplicationId { get; init; }

    public required string PayloadDigest { get; init; }

    public required DateTimeOffset IssuedAt { get; init; }

    public required DateTimeOffset ExpiresAt { get; init; }

    public required string Nonce { get; init; }

    public required int MaxUses { get; init; }

    public required string Authenticator { get; init; }
}

public sealed class BrokerAuthorizationException : Exception
{
    public BrokerAuthorizationException(string code)
        : base(code)
    {
        Code = code;
    }

    public string Code { get; }
}

public sealed class BrokerGrantAuthority
{
    private const int KeyBytes = 32;
    private const int MaximumReplayEntries = 4096;
    private static readonly TimeSpan MaximumLifetime = TimeSpan.FromMinutes(2);
    private static readonly TimeSpan MaximumClockSkew = TimeSpan.FromSeconds(5);

    private readonly byte[] _key;
    private readonly Func<DateTimeOffset> _clock;
    private readonly Dictionary<string, DateTimeOffset> _consumed = new(StringComparer.Ordinal);
    private readonly object _replayLock = new();

    public BrokerGrantAuthority(
        ReadOnlySpan<byte> key,
        Func<DateTimeOffset>? clock = null)
    {
        if (key.Length != KeyBytes)
        {
            throw new ArgumentException("grant_key_must_be_32_bytes", nameof(key));
        }

        _key = key.ToArray();
        _clock = clock ?? (() => DateTimeOffset.UtcNow);
    }

    public static BrokerGrantAuthority FromDefaultStore()
    {
        return new BrokerGrantAuthority(BrokerKeyStore.LoadOrCreateDefault());
    }

    public BrokerCapabilityGrant Issue(
        Guid sessionId,
        Guid taskId,
        Guid approvalId,
        string action,
        string applicationId,
        string payloadDigest,
        TimeSpan? lifetime = null)
    {
        TimeSpan requestedLifetime = lifetime ?? TimeSpan.FromSeconds(30);
        if (requestedLifetime <= TimeSpan.Zero || requestedLifetime > MaximumLifetime)
        {
            throw new ArgumentOutOfRangeException(
                nameof(lifetime),
                "grant_lifetime_invalid");
        }

        DateTimeOffset issuedAt = _clock().ToUniversalTime();
        BrokerCapabilityGrant unsigned = new()
        {
            SchemaVersion = BrokerProtocol.SchemaVersion,
            GrantId = Guid.NewGuid(),
            SessionId = sessionId,
            TaskId = taskId,
            ApprovalId = approvalId,
            Action = action,
            ApplicationId = applicationId,
            PayloadDigest = payloadDigest,
            IssuedAt = issuedAt,
            ExpiresAt = issuedAt + requestedLifetime,
            Nonce = Convert.ToHexString(RandomNumberGenerator.GetBytes(16)).ToLowerInvariant(),
            MaxUses = 1,
            Authenticator = new string('0', 64),
        };
        ValidateShape(unsigned);
        return unsigned with { Authenticator = Authenticate(unsigned) };
    }

    public void Validate(
        BrokerCapabilityGrant grant,
        string expectedAction,
        string expectedApplicationId)
    {
        ArgumentNullException.ThrowIfNull(grant);
        ValidateShape(grant);
        DateTimeOffset now = _clock().ToUniversalTime();
        if (grant.IssuedAt > now + MaximumClockSkew)
        {
            throw new BrokerAuthorizationException("capability_not_yet_valid");
        }

        if (grant.ExpiresAt <= now)
        {
            throw new BrokerAuthorizationException("capability_expired");
        }

        if (grant.ExpiresAt - grant.IssuedAt > MaximumLifetime)
        {
            throw new BrokerAuthorizationException("capability_lifetime_exceeded");
        }

        if (!StringComparer.Ordinal.Equals(grant.Action, expectedAction))
        {
            throw new BrokerAuthorizationException("capability_action_mismatch");
        }

        if (!StringComparer.Ordinal.Equals(grant.ApplicationId, expectedApplicationId))
        {
            throw new BrokerAuthorizationException("capability_resource_mismatch");
        }

        byte[] supplied;
        try
        {
            supplied = Convert.FromHexString(grant.Authenticator);
        }
        catch (FormatException)
        {
            throw new BrokerAuthorizationException("capability_authenticator_invalid");
        }

        byte[] expected = Convert.FromHexString(Authenticate(grant));
        if (!CryptographicOperations.FixedTimeEquals(supplied, expected))
        {
            throw new BrokerAuthorizationException("capability_authenticator_mismatch");
        }
    }

    public void Consume(
        BrokerCapabilityGrant grant,
        string expectedAction,
        string expectedApplicationId)
    {
        Validate(grant, expectedAction, expectedApplicationId);
        string replayKey = $"{grant.GrantId:N}:{grant.Nonce}";
        DateTimeOffset now = _clock().ToUniversalTime();
        lock (_replayLock)
        {
            foreach (string expired in _consumed
                .Where(item => item.Value <= now)
                .Select(item => item.Key)
                .ToArray())
            {
                _consumed.Remove(expired);
            }

            if (_consumed.ContainsKey(replayKey))
            {
                throw new BrokerAuthorizationException("capability_replayed");
            }

            if (_consumed.Count >= MaximumReplayEntries)
            {
                throw new BrokerAuthorizationException("capability_replay_cache_full");
            }

            _consumed.Add(replayKey, grant.ExpiresAt);
        }
    }

    private string Authenticate(BrokerCapabilityGrant grant)
    {
        using MemoryStream stream = new();
        using (Utf8JsonWriter writer = new(stream))
        {
            writer.WriteStartObject();
            writer.WriteString("schema_version", grant.SchemaVersion);
            writer.WriteString("grant_id", grant.GrantId);
            writer.WriteString("session_id", grant.SessionId);
            writer.WriteString("task_id", grant.TaskId);
            writer.WriteString("approval_id", grant.ApprovalId);
            writer.WriteString("action", grant.Action);
            writer.WriteString("application_id", grant.ApplicationId);
            writer.WriteString("payload_digest", grant.PayloadDigest);
            writer.WriteString("issued_at", grant.IssuedAt.ToUniversalTime());
            writer.WriteString("expires_at", grant.ExpiresAt.ToUniversalTime());
            writer.WriteString("nonce", grant.Nonce);
            writer.WriteNumber("max_uses", grant.MaxUses);
            writer.WriteEndObject();
        }

        return Convert.ToHexString(HMACSHA256.HashData(_key, stream.ToArray()))
            .ToLowerInvariant();
    }

    private static void ValidateShape(BrokerCapabilityGrant grant)
    {
        if (grant.SchemaVersion != BrokerProtocol.SchemaVersion)
        {
            throw new BrokerAuthorizationException("capability_schema_unsupported");
        }

        if (grant.GrantId == Guid.Empty ||
            grant.SessionId == Guid.Empty ||
            grant.TaskId == Guid.Empty ||
            grant.ApprovalId == Guid.Empty)
        {
            throw new BrokerAuthorizationException("capability_identifier_invalid");
        }

        if (grant.Action is not (
            "windows.application.open" or "windows.application.close"))
        {
            throw new BrokerAuthorizationException("capability_action_invalid");
        }

        if (!IsLowerHex(grant.PayloadDigest, 64) ||
            !IsLowerHex(grant.Nonce, 32) ||
            !IsLowerHex(grant.Authenticator, 64))
        {
            throw new BrokerAuthorizationException("capability_encoding_invalid");
        }

        if (grant.MaxUses != 1 || grant.ExpiresAt <= grant.IssuedAt)
        {
            throw new BrokerAuthorizationException("capability_bounds_invalid");
        }

        if (string.IsNullOrWhiteSpace(grant.ApplicationId) || grant.ApplicationId.Length > 64)
        {
            throw new BrokerAuthorizationException("capability_resource_invalid");
        }
    }

    private static bool IsLowerHex(string value, int length)
    {
        return value.Length == length && value.All(character =>
            character is >= '0' and <= '9' or >= 'a' and <= 'f');
    }
}
