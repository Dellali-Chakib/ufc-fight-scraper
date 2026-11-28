"""Favorite aliases require corroborated legacy identity, never a unique name."""
import copy
import unittest
from scraper.identity import reconcile

BASE='https://www.ufc.com/athlete/'
OLD='0123456789abcdef'
OTHER='fedcba9876543210'


def legacy(fid=OLD,number=7,dob='1980-01-01',name='Same Name'):
    return {'fighter_id':fid,'id':number,'name':name,'dob':dob,
            'url':'http://ufcstats.com/fighter-details/'+fid,'source_id':None,'favorite_aliases':None}


def profile(sid='55',dob='1980-01-01',name='Same Name'):
    return {'source_id':sid,'url':BASE+sid,'name':name,'dob':dob}


class FavoriteAliasTests(unittest.TestCase):
    def test_conflicting_or_missing_dob_never_exports_name_or_numeric_fallback(self):
        for dob in ['1981-01-01',None]:
            with self.subTest(dob=dob):
                registry={OLD:legacy()};p=profile(dob=dob);report={}
                reconcile([p],registry,{},report)
                self.assertEqual(p['fighter_id'],'ufc-55')
                self.assertIsNone(p['favorite_aliases'])
                self.assertIsNone(registry['ufc-55']['favorite_aliases'])
                self.assertIn(p['url'],report['ambiguous'])
                self.assertEqual(registry[OLD]['id'],7)

    def test_corroborated_legacy_and_reviewed_migrations_keep_supported_keys(self):
        for dob,aliases in [('1980-01-01',{}),('1981-01-01',{'55':OLD})]:
            registry={OLD:legacy()};p=profile(dob=dob)
            reconcile([p],registry,aliases,{})
            self.assertEqual(p['fighter_id'],OLD)
            self.assertEqual(p['favorite_aliases'],'7 same-name')
            # A later canonical URL/name change retains established aliases.
            p.update(url=BASE+'renamed',name='Updated Name')
            reconcile([p],registry,{}, {})
            self.assertEqual(p['fighter_id'],OLD)
            self.assertEqual(set(p['favorite_aliases'].split()),{'7','same-name'})

    def test_hidden_competing_identity_blocks_alias_for_visible_matched_fighter(self):
        registry={OLD:legacy(),OTHER:legacy(OTHER,8,'1970-01-01')}
        p=profile();reconcile([p],registry,{}, {})
        self.assertEqual(p['fighter_id'],OLD)
        self.assertEqual(p['favorite_aliases'],'7')

    def test_ambiguous_source_cannot_resolve_through_another_same_name_export(self):
        registry={OLD:legacy()};matched=profile();uncertain=profile('56','1981-01-01')
        reconcile([matched,uncertain],registry,{}, {})
        self.assertEqual(matched['favorite_aliases'],'7')
        self.assertIsNone(uncertain['favorite_aliases'])
        # The policy remains stable on incremental checks of the matched row.
        reconcile([matched],registry,{}, {})
        self.assertEqual(matched['favorite_aliases'],'7')

    def test_old_unsafe_ufc_generated_aliases_are_not_carried_forward(self):
        p=profile();registry={'ufc-55':dict(p,fighter_id='ufc-55',id=100,
                                          favorite_aliases='100 same-name')}
        reconcile([p],registry,{}, {})
        self.assertEqual(p['fighter_id'],'ufc-55')
        self.assertIsNone(p['favorite_aliases'])

    def test_later_source_display_names_do_not_invent_historic_aliases(self):
        registry={OLD:legacy(name='José Name')}
        p=profile(name='Jose Name')
        for _ in range(4):
            reconcile([p],registry,{}, {})
            self.assertEqual(p['fighter_id'],OLD)
            self.assertEqual(set(p['favorite_aliases'].split()),{'7','jos-name'})
            self.assertNotIn('jose-name',p['favorite_aliases'].split())

    def test_old_candidate_alias_policy_is_rejected_without_publishing(self):
        from scraper.identity import validate_favorite_aliases
        from scraper.contract import Fighter
        from scraper.stat_scraper import collect_profile
        from test_refresh import Pages, terminal, fixture, TODAY
        url=BASE+'kayla-harrison'
        fields,_=collect_profile(Pages({url:terminal(fixture('kayla-harrison'))}),url,TODAY)
        unsafe=Fighter.model_validate(dict(fields,fighter_id='ufc-136296',favorite_aliases='100 kayla-harrison'))
        with self.assertRaisesRegex(ValueError,'regenerate candidate'):
            validate_favorite_aliases({unsafe.fighter_id:unsafe},{},{})
        safe=unsafe.model_copy(update={'favorite_aliases':None})
        validate_favorite_aliases({safe.fighter_id:safe},{},{})

    def test_order_and_ascii_slug_collisions_do_not_choose_a_name_target(self):
        a=legacy(name='Name One');b=legacy(OTHER,8,name='Name-One')
        expected=None
        for profiles in [[profile(name='Name One'),profile('56',name='Name-One')],
                         [profile('56',name='Name-One'),profile(name='Name One')]]:
            registry={OLD:copy.deepcopy(a),OTHER:copy.deepcopy(b)}
            reconcile(profiles,registry,{}, {})
            aliases={p['fighter_id']:p['favorite_aliases'] for p in profiles}
            self.assertEqual(set(aliases.values()),{'7','8'})
            if expected is None:expected=aliases
            self.assertEqual(aliases,expected)


if __name__=='__main__':unittest.main()
