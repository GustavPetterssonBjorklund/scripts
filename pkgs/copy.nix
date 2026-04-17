{ lib, python3, stdenv, wl-clipboard, writeShellApplication, xclip, xsel }:

writeShellApplication {
  name = "copy";

  runtimeInputs =
    [ python3 ]
    ++ lib.optionals stdenv.isLinux [
      wl-clipboard
      xclip
      xsel
    ];

  text = ''
    exec python3 ${../tools/copy/copy.py} "$@"
  '';

  meta = {
    description = "Copy stdin, arguments, or the previous tmux command transcript to the clipboard";
    homepage = "https://github.com/GustavPetterssonBjorklund/scripts";
    mainProgram = "copy";
    platforms = lib.platforms.unix;
  };
}
