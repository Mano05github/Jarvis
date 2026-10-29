# Native components

`Jarvis.WindowsBroker` is the constrained .NET 8 Windows capability boundary. Its current
increment exposes a current-user-only named pipe, verifies the connected caller SID, applies
a strict 64 KiB protocol limit, validates DPAPI-backed HMAC capability grants, and denies every
action because real execution is not yet certified. It never exposes a shell.

Run its dependency-free contract checks from the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-windows-broker.ps1
```

