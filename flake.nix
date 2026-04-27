{
  description = "Small CLI utilities packaged as a Nix flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
  };

  outputs = { self, nixpkgs }:
    let
      lib = nixpkgs.lib;
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = f: lib.genAttrs systems (system: f system);
    in
    {
      formatter = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        pkgs.nixfmt-rfc-style
      );

      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        rec {
          copy = pkgs.callPackage ./pkgs/copy.nix { };
          gitx = pkgs.callPackage ./pkgs/gitx.nix { };
          ovpntmp = pkgs.callPackage ./pkgs/ovpntmp.nix { };
          redact = pkgs.callPackage ./pkgs/redact.nix { };
          default = gitx;
        }
      );

      apps = forAllSystems (system:
        let
          packages = self.packages.${system};
          copyApp = {
            type = "app";
            program = "${packages.copy}/bin/copy";
          };
          gitxApp = {
            type = "app";
            program = "${packages.gitx}/bin/gitx";
          };
          ovpntmpApp = {
            type = "app";
            program = "${packages.ovpntmp}/bin/ovpntmp";
          };
          redactApp = {
            type = "app";
            program = "${packages.redact}/bin/redact";
          };
        in
        {
          copy = copyApp;
          gitx = gitxApp;
          ovpntmp = ovpntmpApp;
          redact = redactApp;
          default = gitxApp;
        }
      );

      checks = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          packages = self.packages.${system};
        in
        {
          inherit (packages) copy gitx ovpntmp redact;

          copy-help = pkgs.runCommand "copy-help" {
            nativeBuildInputs = [ packages.copy ];
          } ''
            copy --help > "$out"
          '';

          copy-tests = pkgs.runCommand "copy-tests" {
            nativeBuildInputs = [ pkgs.python3 ];
          } ''
            python - <<'PY'
            import argparse
            import importlib.util
            from unittest.mock import patch

            module_path = "${./tools/copy/copy.py}"
            module_spec = importlib.util.spec_from_file_location("copy_tool", module_path)
            assert module_spec is not None and module_spec.loader is not None
            copy_module = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(copy_module)


            def assert_equal(left, right):
                if left != right:
                    raise AssertionError(f"expected {right!r}, got {left!r}")


            parser = argparse.ArgumentParser(prog="copy")

            args = argparse.Namespace(primary=False, text=["Hello", "World"])
            with patch.object(copy_module, "stdin_has_data", return_value=True):
                with patch.object(copy_module, "read_tmux_previous_command", return_value="tmux text\n"):
                    with patch.object(copy_module.sys, "stdin") as fake_stdin:
                        fake_stdin.read.return_value = "stdin text\n"
                        assert_equal(copy_module.resolve_text(args, parser), "Hello World")

            args = argparse.Namespace(primary=False, text=[])
            with patch.object(copy_module, "stdin_has_data", return_value=True):
                with patch.object(copy_module, "read_tmux_previous_command", return_value="tmux text\n"):
                    with patch.object(copy_module.sys, "stdin") as fake_stdin:
                        fake_stdin.read.return_value = "stdin text\n"
                        assert_equal(copy_module.resolve_text(args, parser), "stdin text\n")

            args = argparse.Namespace(primary=True, text=[])
            with patch.object(copy_module, "stdin_has_data", return_value=False):
                with patch.object(copy_module, "read_tmux_previous_command", return_value="tmux text\n") as read_tmux:
                    assert_equal(copy_module.resolve_text(args, parser), "tmux text\n")
                    read_tmux.assert_called_once_with(["copy", "copy --primary", "copy -p"])
            PY
            touch "$out"
          '';

          gitx-help = pkgs.runCommand "gitx-help" {
            nativeBuildInputs = [ packages.gitx ];
          } ''
            gitx -h > "$out"
          '';

          ovpntmp-syntax = pkgs.runCommand "ovpntmp-syntax" {
            nativeBuildInputs = [ pkgs.bash ];
          } ''
            bash -n ${./tools/ovpntmp/ovpntmp.sh}
            touch "$out"
          '';

          redact-help = pkgs.runCommand "redact-help" {
            nativeBuildInputs = [ packages.redact ];
          } ''
            redact --help > "$out"
          '';

          redact-auto = pkgs.runCommand "redact-auto" {
            nativeBuildInputs = [ packages.redact ];
          } ''
            output="$(printf 'email=test@example.com\ntoken=sk-exampleSecretValue123456789\n' | redact --yes)"
            case "$output" in
              *"<redacted>"*) ;;
              *)
                echo "expected redacted output"
                exit 1
                ;;
            esac
            touch "$out"
          '';
        }
      );

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              git
              nixfmt-rfc-style
              python3
              shellcheck
              shfmt
            ];
          };
        }
      );
    };
}
