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
          gitx = pkgs.callPackage ./pkgs/gitx.nix { };
          ovpntmp = pkgs.callPackage ./pkgs/ovpntmp.nix { };
          redact = pkgs.callPackage ./pkgs/redact.nix { };
          default = gitx;
        }
      );

      apps = forAllSystems (system:
        let
          packages = self.packages.${system};
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
          inherit (packages) gitx ovpntmp redact;

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
