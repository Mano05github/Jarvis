using System.IO.Pipes;
using System.Security.Principal;

namespace Jarvis.WindowsBroker;

public sealed class BrokerServer
{
    public const string Version = "0.1.0";

    private readonly string _pipeName;
    private readonly string _ownerSid;
    private readonly BrokerGrantAuthority _grantAuthority;

    public BrokerServer(
        string? pipeName = null,
        BrokerGrantAuthority? grantAuthority = null)
    {
        _ownerSid = BrokerIdentity.CurrentUserSid();
        _grantAuthority = grantAuthority ?? BrokerGrantAuthority.FromDefaultStore();
        _pipeName = pipeName ?? BrokerIdentity.DefaultPipeName();
        if (_pipeName.Length is < 1 or > 200 || _pipeName.IndexOfAny(['/', '\\']) >= 0)
        {
            throw new ArgumentException("pipe_name_invalid", nameof(pipeName));
        }
    }

    public string PipeName => _pipeName;

    public async Task HandleOneClientAsync(CancellationToken cancellationToken)
    {
        await using NamedPipeServerStream pipe = new(
            _pipeName,
            PipeDirection.InOut,
            1,
            PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous | PipeOptions.WriteThrough | PipeOptions.CurrentUserOnly,
            BrokerProtocol.MaximumMessageBytes,
            BrokerProtocol.MaximumMessageBytes);

        await pipe.WaitForConnectionAsync(cancellationToken).ConfigureAwait(false);
        string callerSid;
        try
        {
            callerSid = BrokerIdentity.ConnectedClientSid(pipe);
        }
        catch (Exception error) when (
            error is IOException or
                UnauthorizedAccessException or
                InvalidOperationException or
                IdentityNotMappedException)
        {
            await WriteFailureAsync(
                pipe,
                Guid.Empty,
                "caller_identity_unavailable",
                null,
                cancellationToken).ConfigureAwait(false);
            return;
        }

        if (!StringComparer.Ordinal.Equals(callerSid, _ownerSid))
        {
            await WriteFailureAsync(
                pipe,
                Guid.Empty,
                "caller_identity_denied",
                callerSid,
                cancellationToken).ConfigureAwait(false);
            return;
        }

        Guid requestId = Guid.Empty;
        try
        {
            BrokerRequest request = await BrokerProtocol.ReadAsync<BrokerRequest>(
                pipe,
                cancellationToken).ConfigureAwait(false);
            requestId = request.RequestId;
            request.Validate();

            BrokerResponse response;
            if (request.Operation == "broker.health")
            {
                response = new BrokerResponse
                {
                    SchemaVersion = BrokerProtocol.SchemaVersion,
                    RequestId = request.RequestId,
                    Status = "ok",
                    Code = "broker_ready_execution_disabled",
                    BrokerVersion = Version,
                    CallerSid = callerSid,
                };
            }
            else
            {
                try
                {
                    _grantAuthority.Validate(
                        request.CapabilityGrant!,
                        request.Operation,
                        request.ApplicationId!);
                }
                catch (BrokerAuthorizationException error)
                {
                    await WriteFailureAsync(
                        pipe,
                        request.RequestId,
                        error.Code,
                        callerSid,
                        cancellationToken).ConfigureAwait(false);
                    return;
                }

                response = new BrokerResponse
                {
                    SchemaVersion = BrokerProtocol.SchemaVersion,
                    RequestId = request.RequestId,
                    Status = "denied",
                    Code = "execution_disabled",
                    BrokerVersion = Version,
                    CallerSid = callerSid,
                };
            }
            await BrokerProtocol.WriteAsync(pipe, response, cancellationToken)
                .ConfigureAwait(false);
        }
        catch (BrokerProtocolException error)
        {
            await WriteFailureAsync(
                pipe,
                requestId,
                error.Code,
                callerSid,
                cancellationToken).ConfigureAwait(false);
        }
    }

    private static Task WriteFailureAsync(
        Stream pipe,
        Guid requestId,
        string code,
        string? callerSid,
        CancellationToken cancellationToken)
    {
        return BrokerProtocol.WriteAsync(
            pipe,
            new BrokerResponse
            {
                SchemaVersion = BrokerProtocol.SchemaVersion,
                RequestId = requestId,
                Status = "error",
                Code = code,
                BrokerVersion = Version,
                CallerSid = callerSid,
            },
            cancellationToken);
    }
}
