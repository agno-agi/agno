import { test } from 'node:test';
import assert from 'node:assert/strict';
import { hasProfanity, cleanName, cleanChat } from '../src/core/profanity.js';

test('küfür yakalanır: düz, harf değişimi, ayraç, tekrar', () => {
  for (const t of ['siktir git', 'SİKTİR', 's1kt1r', 's i k t i r', 'o.r.o.s.p.u', 'oruuuspu çocuğu', 'amk', 'a m k', 'yarrak', 'piç', 'göt', 'fuck you', 'f u c k', 'sh1t', 'amına koyayım', 'orospu_cocugu']) {
    assert.ok(hasProfanity(t), t);
  }
});
test('masum kelimeler geçer', () => {
  for (const t of ['şikayet', 'Allah rahmet eylesin', 'başımız sağolsun', 'siklon', 'sikke', 'gotik', 'pusula', 'Mekanı cennet olsun', 'mkn', 'Amin', 'Ahmet', 'Çakır ailesine başsağlığı', '🙏🙏', 'Gül', 'Süleyman amca']) {
    assert.ok(!hasProfanity(t), t);
  }
});
test('isim ve sohbet temizliği, ek kelime listesi', () => {
  assert.equal(cleanName('orospu123'), 'Misafir');
  assert.equal(cleanName('Ayşe'), 'Ayşe');
  assert.equal(cleanChat('siktir'), '');
  assert.equal(cleanChat('Başımız sağolsun'), 'Başımız sağolsun');
  assert.ok(hasProfanity('zırtapoz', ['zırtapoz']));
});
