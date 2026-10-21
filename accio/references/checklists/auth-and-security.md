# Auth and security

- Trace every input the change reads from outside (request, file, environment, another service) to where it is
  used. Is it validated, escaped or parameterised before it reaches a query, a shell, a path or HTML?
- For each new endpoint or action: who may call it? Find the check in the code, and a test that calls it as the
  wrong user and expects a refusal.
- Look for secrets: keys or tokens in code, tests, logs or error messages. Values must come from the environment.
- Check comparisons of secrets and tokens are constant-time, and that tokens expire and are single-use where the
  DoD says so.
- When one part checks a URL or path and another reads it again (browser, server, file system), try inputs the two
  may read differently: `\`, `@`, `%2f`, `%5c`, `..`. For example `http://evil.com\@host:port/`.
- Check failure paths fail closed: an error, a timeout or a missing field must deny, not allow.
- Check what the change logs: no passwords, tokens or personal data.
