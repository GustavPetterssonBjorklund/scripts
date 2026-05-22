{ lib, git, python3, symlinkJoin, writeShellApplication }:

let
  gitx = writeShellApplication {
    name = "gitx";

    runtimeInputs = [
      git
      python3
    ];

    text = ''
      exec python3 ${../tools/gitx}/gitx.py "$@"
    '';
  };
in
symlinkJoin {
  name = "gitx";
  paths = [ gitx ];

  postBuild = ''
    ln -s gitx "$out/bin/g"
  '';

  meta = {
    description = "Short aliases for common git commands";
    homepage = "https://github.com/GustavPetterssonBjorklund/scripts";
    mainProgram = "gitx";
    platforms = lib.platforms.unix;
  };
}
