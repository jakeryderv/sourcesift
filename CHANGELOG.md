# Changelog

Release Please maintains this file through reviewed release PRs.

## [0.7.0](https://github.com/jakeryderv/sourcesift/compare/v0.6.0...v0.7.0) (2026-11-25)


### ⚠ BREAKING CHANGES

* lay the web app out as chats, chat, and an artifact pane with export ([#48](https://github.com/jakeryderv/sourcesift/issues/48))
* save each conversation in its own folder, with a list to reopen from ([#47](https://github.com/jakeryderv/sourcesift/issues/47))
* replace widgets and reports with figures and artifacts ([#46](https://github.com/jakeryderv/sourcesift/issues/46))
* remove the terminal chat and make the web app the interactive interface ([#45](https://github.com/jakeryderv/sourcesift/issues/45))
* draw visuals with Plotly from tables and drop automatic refresh ([#43](https://github.com/jakeryderv/sourcesift/issues/43))
* add typed data sources, widgets, and visuals in results ([#39](https://github.com/jakeryderv/sourcesift/issues/39))

### Features

* add a weather source and a map widget with live radar ([#41](https://github.com/jakeryderv/sourcesift/issues/41)) ([19d5e01](https://github.com/jakeryderv/sourcesift/commit/19d5e018e29f09b4046557e07f4d90f7acfd0889))
* add typed data sources, widgets, and visuals in results ([#39](https://github.com/jakeryderv/sourcesift/issues/39)) ([d260aa1](https://github.com/jakeryderv/sourcesift/commit/d260aa18b43ba04db3d0f11cda2ba61debf4c34e))
* **chat:** add /sources to browse the catalog and limit a conversation's sources ([#36](https://github.com/jakeryderv/sourcesift/issues/36)) ([de38fb8](https://github.com/jakeryderv/sourcesift/commit/de38fb8986fe04ad971c65cf3d546081b8efe05e))
* draw visuals with Plotly from tables and drop automatic refresh ([#43](https://github.com/jakeryderv/sourcesift/issues/43)) ([b416cdb](https://github.com/jakeryderv/sourcesift/commit/b416cdbc621939581c20f564ea8fb09eee3baf32))
* include visuals in reports, with chart images from the web app ([#44](https://github.com/jakeryderv/sourcesift/issues/44)) ([a030878](https://github.com/jakeryderv/sourcesift/commit/a030878a7fb9a5ae0ab50786bcf1b8845bb5e387))
* lay the web app out as chats, chat, and an artifact pane with export ([#48](https://github.com/jakeryderv/sourcesift/issues/48)) ([f47e574](https://github.com/jakeryderv/sourcesift/commit/f47e574f5ca628928aebd0022e0670ddbb1f33b4))
* remove the terminal chat and make the web app the interactive interface ([#45](https://github.com/jakeryderv/sourcesift/issues/45)) ([804ac1e](https://github.com/jakeryderv/sourcesift/commit/804ac1e62f33d75d602563626fcac343f705a2f5))
* replace widgets and reports with figures and artifacts ([#46](https://github.com/jakeryderv/sourcesift/issues/46)) ([88a355d](https://github.com/jakeryderv/sourcesift/commit/88a355dbd0b72fdfdba78115922c60f8a9af5c37))
* save each conversation in its own folder, with a list to reopen from ([#47](https://github.com/jakeryderv/sourcesift/issues/47)) ([b2bdfda](https://github.com/jakeryderv/sourcesift/commit/b2bdfda3e97a3177ee5379397ec942b0e4c8d9bd))
* **web:** add ssift web, a local page that draws charts, tables, and figures ([#40](https://github.com/jakeryderv/sourcesift/issues/40)) ([39a3c8e](https://github.com/jakeryderv/sourcesift/commit/39a3c8e0108cfcb90e6faa702e85c26cce985f4b))
* **web:** show agent activity, group visuals in one card, and restyle the chat ([#42](https://github.com/jakeryderv/sourcesift/issues/42)) ([45b3bfc](https://github.com/jakeryderv/sourcesift/commit/45b3bfc756a19809eca736eb5e21c1ee9376d60c))


### Documentation

* describe artifacts, figures, saved conversations, and the web layout ([#49](https://github.com/jakeryderv/sourcesift/issues/49)) ([3ae95ee](https://github.com/jakeryderv/sourcesift/commit/3ae95ee148d70018758a48c648a6d9fac6adbd9c))
* propose a local web app with typed data sources and display blocks ([#38](https://github.com/jakeryderv/sourcesift/issues/38)) ([e6438c5](https://github.com/jakeryderv/sourcesift/commit/e6438c5b019e74110eabf726af6ad0aa2dc46cb6))

## [0.6.0](https://github.com/jakeryderv/sourcesift/compare/v0.5.0...v0.6.0) (2026-11-21)


### Features

* **chat:** add /read and /evidence and reuse feeds within a conversation ([#30](https://github.com/jakeryderv/sourcesift/issues/30)) ([ca438fd](https://github.com/jakeryderv/sourcesift/commit/ca438fdacc52827ac139fb3d08c41ae9116d538b))
* **chat:** add opt-in saved conversations with --save and --continue ([#33](https://github.com/jakeryderv/sourcesift/issues/33)) ([5fd8f54](https://github.com/jakeryderv/sourcesift/commit/5fd8f547e84f95e5ff9ac6bc98c52dd29f712818))
* **cli:** add --json output for ask ([#28](https://github.com/jakeryderv/sourcesift/issues/28)) ([2899169](https://github.com/jakeryderv/sourcesift/commit/2899169f184d2ab471c1613e15f29fa41cfdccc3))
* save answers as Markdown reports ([#29](https://github.com/jakeryderv/sourcesift/issues/29)) ([2b5f06b](https://github.com/jakeryderv/sourcesift/commit/2b5f06b2ffc9b73b495f50e4268bdc81855ac3a3))
* **sources:** add 20 feeds for world news, science, health, tech, and policy ([#31](https://github.com/jakeryderv/sourcesift/issues/31)) ([9f27444](https://github.com/jakeryderv/sourcesift/commit/9f27444ed4142335328585e1318be4774f92acfb))
* **sources:** add live data sources for Hacker News and US Treasury ([#32](https://github.com/jakeryderv/sourcesift/issues/32)) ([6885970](https://github.com/jakeryderv/sourcesift/commit/6885970852acf08d341f9839ea7acba308b573e1))


### Bug Fixes

* silence the urllib3 SOCKS warning printed on every command ([#35](https://github.com/jakeryderv/sourcesift/issues/35)) ([1133ecb](https://github.com/jakeryderv/sourcesift/commit/1133ecb3f9d12b34125b0c8dc4b18efae28a99fa))
* surface provider error reasons and use a bare User-Agent ([#27](https://github.com/jakeryderv/sourcesift/issues/27)) ([e7ab60c](https://github.com/jakeryderv/sourcesift/commit/e7ab60cdf60c41b802edcfb60df377a3e145f639))


### Documentation

* add Quarto architecture overview ([#25](https://github.com/jakeryderv/sourcesift/issues/25)) ([49a8d9d](https://github.com/jakeryderv/sourcesift/commit/49a8d9dee74887a171c192f6a1c192743f0d690e))
* record the follow-up round in the roadmap and README ([#34](https://github.com/jakeryderv/sourcesift/issues/34)) ([fe05b52](https://github.com/jakeryderv/sourcesift/commit/fe05b52788208dc051c8ca6ce9735f8df12989f9))

## [0.5.0](https://github.com/jakeryderv/sourcesift/compare/v0.4.0...v0.5.0) (2026-10-15)


### Features

* **chat:** complete model IDs from the OpenRouter catalog ([#23](https://github.com/jakeryderv/sourcesift/issues/23)) ([2d269fe](https://github.com/jakeryderv/sourcesift/commit/2d269fe49d093f168325bc54c5cba219d38632bc))

## [0.4.0](https://github.com/jakeryderv/sourcesift/compare/v0.3.2...v0.4.0) (2026-10-15)


### Features

* **chat:** add fuzzy command and file pickers with interactive setup ([#21](https://github.com/jakeryderv/sourcesift/issues/21)) ([f73edc2](https://github.com/jakeryderv/sourcesift/commit/f73edc2e163470d690ac886bcdc88263fd02a78b))

## [0.3.2](https://github.com/jakeryderv/sourcesift/compare/v0.3.1...v0.3.2) (2026-10-15)


### Bug Fixes

* **chat:** use conventional prompt and slash command controls ([#19](https://github.com/jakeryderv/sourcesift/issues/19)) ([e9344f9](https://github.com/jakeryderv/sourcesift/commit/e9344f98d300c1d15b59e74d6f06404362709664))

## [0.3.1](https://github.com/jakeryderv/sourcesift/compare/v0.3.0...v0.3.1) (2026-10-15)


### Bug Fixes

* **chat:** harden cancellation and session checks ([#17](https://github.com/jakeryderv/sourcesift/issues/17)) ([b6ffa23](https://github.com/jakeryderv/sourcesift/commit/b6ffa23b04cf77fe379466cc224c2c142d359fb0))

## [0.3.0](https://github.com/jakeryderv/sourcesift/compare/v0.2.0...v0.3.0) (2026-10-15)


### Features

* **chat:** add interactive research sessions and terminal UI ([#15](https://github.com/jakeryderv/sourcesift/issues/15)) ([84a764f](https://github.com/jakeryderv/sourcesift/commit/84a764fa978981702528bcd4ff6f7bca85e8125a))

## [0.2.0](https://github.com/jakeryderv/sourcesift/compare/v0.1.0...v0.2.0) (2026-10-15)


### Features

* **research:** add registered sources and grounded research ([#13](https://github.com/jakeryderv/sourcesift/issues/13)) ([d4b33d4](https://github.com/jakeryderv/sourcesift/commit/d4b33d4bcba6515b760964e7bc6b24dc210a9ecc))

## [0.1.0](https://github.com/jakeryderv/sourcesift/compare/v0.0.2...v0.1.0) (2026-10-14)


### Features

* add composable ssift command line interface ([#11](https://github.com/jakeryderv/sourcesift/issues/11)) ([8c8cf13](https://github.com/jakeryderv/sourcesift/commit/8c8cf13c187e102552a47dcbbfc54de29d8b04f7))
* add configuration and bounded request context ([#8](https://github.com/jakeryderv/sourcesift/issues/8)) ([89bb489](https://github.com/jakeryderv/sourcesift/commit/89bb48902aa24a3e1013a721861227ea38680571))
* implement bounded OpenRouter agent SDK ([#10](https://github.com/jakeryderv/sourcesift/issues/10)) ([ebe44c5](https://github.com/jakeryderv/sourcesift/commit/ebe44c5fdf89a9007f010dc727fddf9b28168d88))

## [0.0.2](https://github.com/jakeryderv/sourcesift/compare/v0.0.1...v0.0.2) (2026-10-14)


### Documentation

* Document the proposed SourceSift architecture and interfaces ([af28858](https://github.com/jakeryderv/sourcesift/commit/af288586b4f5d0639422664571ea392f3e271cb7))
* Add the roadmap and use cases, and separate archived course documents ([43171fc](https://github.com/jakeryderv/sourcesift/commit/43171fc8057b7490f4a55583d0f0654df7d826ba))

### Maintenance

* Add automated release PRs, version and lockfile consistency checks, and package validation across Python 3.11–3.14.

## 0.0.1 (2026-10-14)

### Initial scaffold

- Publish the initial Python package with Apache 2.0 licensing.
- Add uv development checks, Python 3.11–3.14 CI, distribution validation, and PyPI Trusted Publishing.
- Expose the scaffold `hello()` function; research and CLI functionality remain planned.
