{ lib, git, python3, writeShellApplication }:

writeShellApplication {
  name = "gitx";

  runtimeInputs = [
    git
    python3
  ];

  text = ''
    exec python3 ${../tools/gitx/gitx.py} "$@"
  '';

  meta = {
    description = "Short aliases for common git commands";
    homepage = "https://github.com/GustavPetterssonBjorklund/scripts";
    mainProgram = "gitx";
    platforms = lib.platforms.unix;
  };
}
