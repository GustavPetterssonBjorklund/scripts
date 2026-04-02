{ lib, python3, writeShellApplication }:

writeShellApplication {
  name = "redact";

  runtimeInputs = [
    python3
  ];

  text = ''
    exec python3 ${../tools/redact/redact.py} "$@"
  '';

  meta = {
    description = "Interactive stdin redaction utility with sensitivity scoring";
    homepage = "https://github.com/GustavPetterssonBjorklund/scripts";
    mainProgram = "redact";
    platforms = lib.platforms.unix;
  };
}
