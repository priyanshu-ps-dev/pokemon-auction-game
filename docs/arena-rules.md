# Combat, roster, and room rules

## Combat resolution

Pokémon-only matches use the existing level-50 Pokémon engine and resolved learnsets, with type effectiveness, move PP, abilities, and status. Standard and legendary modes use the official species flags from the existing Pokémon data. Alternate species forms are excluded from draft lots. The draft does not implement the full Pokémon competitive ruleset for items, Mega Evolution, or other battle gimmicks.

Anime and MCU fighters act in effective speed order. Physical strength or attack output is compared with the defender’s applicable defense. A larger capability gap has a nonlinear effect on attack damage. Techniques draw from a finite stamina pool. An exhausted fighter spends an action recovering. Shields reduce damage, exact resistance and immunity tags affect matching attacks, and sufficiently faster fighters can avoid contact-only techniques. An attack that cannot overcome a defense can deal zero damage. Anime and MCU automatic matches that reach their turn limit with both teams standing are draws.

The existing per-system transformations and equipment are attached to fighters. A transformation is never a second draft lot. Anime transformations cost stamina and expire after a bounded number of active turns. These costs and durations are game values. The profiles still lack a full model of source-specific prerequisites and drawbacks. Hero identifiers, auction bids, and encyclopedia power ratings are absent from the action resolver.

Mixed matches compare a Pokémon’s level-50 defense with the anime and MCU defense scale. Pokémon type multipliers only apply against Pokémon targets. Ki, chakra, magic, and other systems retain their own tags. There is no implicit conversion between them and no default franchise-wide damage bonus. This is a game model for crossovers. The outcome depends on the selected continuity, documented techniques, and the assumptions encoded in the adapter.

An eligible replacement enters when a team member is defeated. Tournament points record completed match results. Combat MVP ranks actual knockout counts, then logged damage. Best draft value uses damage per dollar paid. The results view surfaces the decisive attack when a knockout ends the match. Some status and support actions still lack contribution attribution.

## Catalog policy

- **MCU** uses the screen appearances listed per fighter in [the versioned roster](../data/mcu_roster.tsv). The row supplies the identity, demonstrated equipment or techniques, and numerical simulation inputs. These values are game estimates. The old comic sources remain available to the legacy combat provider for archived tests and are excluded from room catalogs.
- **Anime** uses the existing set of curated combat records with known techniques, with explicit [continuity overrides](../data/anime_combat_overrides.json) where adjusted. Unverified records remain browseable in the encyclopedia. Sports entries and Death Note’s non-arena cast are excluded from auctions. Existing verified profiles have varying evidence quality and have not all been independently checked against episodes.
- **Pokémon** uses one record per national species number, taking the default form. Pokémon data comes from the existing Pokédex and PokéAPI files.
- **Identity** uses stable IDs, per-franchise normalized names and source aliases for anime, explicit MCU IDs and alias metadata, and national numbers for Pokémon. Normalization folds Unicode case and removes separators and combining marks. Distinct MCU mantle holders are separate identities. The pool never resets on exhaustion.
- **Artwork** uses existing Pokémon and anime artwork references with a generated fallback. MCU entries use locally generated portraits so an MCU character never displays an unrelated comic variant. A complete third-party artwork license audit remains open.

Primary continuity references include the [Marvel on-screen character directory](https://www.marvel.com/characters), [Marvel’s Wanda Maximoff profile](https://www.marvel.com/characters/scarlet-witch-wanda-maximoff/), [Dragon Ball’s official Goku and Beerus anime introduction](https://en.dragon-ball-official.com/news/01_4561.html), and the [Pokémon Pokédex](https://www.pokemon.com/us/pokedex).

## Room state

The server controls lobby, starting, auction, intermission, battle, results, and rematch transitions. It serializes lot validation, settlement, and skip voting under the room lock. Bids carry the current match and lot IDs, and settlement uses one ledger entry per lot. Timers use the server’s deadline and continue during reconnects.

The stage catalog sends only public character identity and artwork. The separate encyclopedia still exposes its historical search statistics. Browser origins are checked, admin authorization is disabled by default, and request sizes and per-connection message rates are bounded.
