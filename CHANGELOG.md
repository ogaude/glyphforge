# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-05

### Added

- Canonicalisation layers with exact glyphfix-math parity.
- Sandboxed pdflatex renderer (Docker, no network, memory caps) with a digest-pinned texlive image.
- Error classes and ambiguity QC that drops samples whose alternative label renders to identical pixels.
- Grammar and mutation sources.
- Declarative recipes and the `glyphforge` CLI.
- Parquet and glyphfix exporters with a leak gate.
- Degradation operations.

[Unreleased]: https://github.com/ogaude/glyphforge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ogaude/glyphforge/releases/tag/v0.1.0
