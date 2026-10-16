# Local fonts

Copy the already downloaded fonts here for the acceptance recipes. Font binaries
are ignored, are not needed by synthetic tests, and must not be published with
game-derived artwork. All the following Google Fonts families use the SIL OFL;
retain their upstream OFL.txt when redistributing fonts separately.

| Family | Upstream source |
| --- | --- |
| Tektur | https://github.com/google/fonts/tree/main/ofl/tektur |
| Oswald | https://github.com/google/fonts/tree/main/ofl/oswald |
| Russo One | https://github.com/google/fonts/tree/main/ofl/russoone |
| Press Start 2P | https://github.com/google/fonts/tree/main/ofl/pressstart2p |
| Lobster | https://github.com/google/fonts/tree/main/ofl/lobster |
| Caveat | https://github.com/google/fonts/tree/main/ofl/caveat |
| Bad Script | https://github.com/google/fonts/tree/main/ofl/badscript |
| Rubik Dirt | https://github.com/google/fonts/tree/main/ofl/rubikdirt |
| Forum | https://github.com/google/fonts/tree/main/ofl/forum |

Non-Google OFL fonts (download the zip from the page, copy the Regular .ttf here):

| Family | File | Upstream source | Used by |
| --- | --- | --- | --- |
| Unutterable (GGBotNet, SIL OFL 1.1) | `Unutterable-Regular.ttf` | https://ggbot.itch.io/unutterable-font | 0629 blood lettering |

`exit.toml` uses Windows Bahnschrift (Bold Condensed); `fuckoff.toml` uses Windows
Comic Sans Bold. These are resolved from `C:/Windows/Fonts`, without copying them.
