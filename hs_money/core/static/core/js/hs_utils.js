/**
 * hs_utils.js — Utilitários JavaScript compartilhados do HS Money.
 */

window.HS = window.HS || {};

/**
 * Normaliza uma descrição de transação para agrupamento:
 * - Remove conteúdo entre parênteses
 * - Remove dígitos e barras
 * - Colapsa espaços extras
 * - Converte para Title Case (primeira letra de cada palavra em maiúscula)
 *
 * Exemplos:
 *   "joab pereira benevides 001/999 (24/02)" → "Joab Pereira Benevides"
 *   "SUPERMERCADO PARC 03/12 (07/01 11:10)"  → "Supermercado Parc"
 *
 * @param {string} desc
 * @returns {string}
 */
HS.normDesc = function (desc) {
  return desc
    .replace(/\([^)]*\)/g, '')   // remove conteúdo entre parênteses
    .replace(/[\d\/]/g, '')      // remove dígitos e barras
    .replace(/\s{2,}/g, ' ')
    .trim()
    .toLowerCase()
    .replace(/(?:^|\s)\S/g, function (c) { return c.toUpperCase(); });
};
