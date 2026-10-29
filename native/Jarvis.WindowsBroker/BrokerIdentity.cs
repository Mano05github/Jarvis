using System.IO.Pipes;
using System.Security.Principal;

namespace Jarvis.WindowsBroker;

public static class BrokerIdentity
{
    public static string CurrentUserSid()
    {
        return WindowsIdentity.GetCurrent(TokenAccessLevels.Query).User?.Value
            ?? throw new InvalidOperationException("current_user_sid_unavailable");
    }

    public static string ConnectedClientSid(NamedPipeServerStream pipe)
    {
        ArgumentNullException.ThrowIfNull(pipe);
        string accountName = pipe.GetImpersonationUserName();
        if (string.IsNullOrWhiteSpace(accountName))
        {
            throw new InvalidOperationException("caller_account_unavailable");
        }

        IdentityReference translated = new NTAccount(accountName).Translate(
            typeof(SecurityIdentifier));
        return translated is SecurityIdentifier sid
            ? sid.Value
            : throw new InvalidOperationException("caller_sid_unavailable");
    }

    public static string DefaultPipeName()
    {
        return $"jarvis.windows-broker.v1.{CurrentUserSid()}";
    }
}
