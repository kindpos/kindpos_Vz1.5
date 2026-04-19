// ═══════════════════════════════════════════════════
//  KINDpos Terminal — Universal Modifier Data
//  HexNav-compatible structure grouped by menu category
//  Ethereal colors — faded echoes of their parent category
//  Nice. Dependable. Yours.
// ═══════════════════════════════════════════════════

export var PREFIXES = [
  { id: 'no',      label: 'No'      },
  { id: 'add',     label: 'Add'     },
  { id: 'sub',     label: 'Sub'     },
  { id: 'extra',   label: 'Extra'   },
  { id: 'on-side', label: 'On Side' },
];

// ── Ethereal palette — 30-40% opacity ghosts of category colors ──
// PIZZA  (#ff4757) → faded rose
// APPS   (#ffd93d) → faded amber
// SUBS   (#C6FFBB) → faded mint
// SIDES  (#70a1ff) → faded periwinkle
// DRINKS (#ffa502) → faded tangerine
// PREP   (universal) → faded lavender

var MOD_COLORS = {
  pizza:  { color: '#7a2832', textColor: '#ffb3b8' },
  apps:   { color: '#7a6a1e', textColor: '#ffe699' },
  subs:   { color: '#4a7a44', textColor: '#d9ffcc' },
  sides:  { color: '#3a5080', textColor: '#b3ccff' },
  drinks: { color: '#7a5201', textColor: '#ffd480' },
  prep:   { color: '#5a3f7a', textColor: '#d0b8ff' },
};

// ── Pizza placement options ──
export var PIZZA_PLACEMENTS = [
  { id: 'whole', label: 'Whole' },
  { id: 'left',  label: 'Left'  },
  { id: 'right', label: 'Right' },
];

// ── Modifier categories in HexNav format ──
// Each category becomes a hex; its items become child hexes on drill-down
// Categories are filtered at runtime by union of selected ticket item categories

var ALL_MOD_CATEGORIES = [
  {
    id: 'mod-prep', label: 'PREP', menuCategories: ['*'],
    color: MOD_COLORS.prep.color, textColor: MOD_COLORS.prep.textColor,
    subcats: [{ id: 'prep-items', label: 'Prep', items: [
      { label: 'Salt',    id: 'salt',        price: 0 },
      { label: 'Pepper',  id: 'pepper',      price: 0 },
      { label: 'Butter',  id: 'butter',      price: 0 },
      { label: 'Oil',     id: 'oil',         price: 0 },
      { label: 'Garlic',  id: 'garlic',      price: 0.50 },
      { label: 'Lemon',   id: 'lemon-prep',  price: 0 },
    ]}],
  },
  {
    id: 'mod-pizza', label: 'PIZZA', menuCategories: ['pizza'],
    color: MOD_COLORS.pizza.color, textColor: MOD_COLORS.pizza.textColor,
    subcats: [{ id: 'pizza-mod-items', label: 'Pizza', items: [
      { label: 'Pepperoni',  id: 'pepperoni',  price: 1.50 },
      { label: 'Sausage',    id: 'sausage',    price: 1.50 },
      { label: 'Mushrooms',  id: 'mushrooms',  price: 1.00 },
      { label: 'Onions',     id: 'onions',     price: 1.00 },
      { label: 'Peppers',    id: 'peppers',    price: 1.00 },
      { label: 'Xtra Cheese',id: 'x-cheese',   price: 2.00 },
      { label: 'Sauce',      id: 'sauce',      price: 0 },
      { label: 'Olives',     id: 'olives',     price: 1.00 },
      { label: 'Bacon',      id: 'bacon-pizza', price: 1.50 },
      { label: 'Anchovies',  id: 'anchovies',  price: 1.50 },
    ]}],
  },
  {
    id: 'mod-apps', label: 'APPS', menuCategories: ['apps'],
    color: MOD_COLORS.apps.color, textColor: MOD_COLORS.apps.textColor,
    subcats: [{ id: 'apps-mod-items', label: 'Apps', items: [
      { label: 'Sauce',   id: 'sauce-apps',  price: 0.50 },
      { label: 'Ranch',   id: 'ranch',       price: 0.75 },
      { label: 'Cheese',  id: 'cheese-apps', price: 1.00 },
      { label: 'Bacon',   id: 'bacon-apps',  price: 2.00 },
      { label: 'Onion',   id: 'onion-apps',  price: 0 },
    ]}],
  },
  {
    id: 'mod-subs', label: 'SUBS', menuCategories: ['subs'],
    color: MOD_COLORS.subs.color, textColor: MOD_COLORS.subs.textColor,
    subcats: [{ id: 'subs-mod-items', label: 'Subs', items: [
      { label: 'Lettuce',   id: 'lettuce',      price: 0 },
      { label: 'Tomato',    id: 'tomato-subs',   price: 0 },
      { label: 'Onion',     id: 'onion-subs',    price: 0 },
      { label: 'Peppers',   id: 'peppers-subs',  price: 0.75 },
      { label: 'Cheese',    id: 'cheese-subs',   price: 1.50 },
      { label: 'Mayo',      id: 'mayo',          price: 0 },
      { label: 'Mustard',   id: 'mustard',       price: 0 },
      { label: 'Oil & Vin', id: 'oil-vin',       price: 0 },
      { label: 'Bacon',     id: 'bacon-subs',    price: 2.00 },
    ]}],
  },
  {
    id: 'mod-sides', label: 'SIDES', menuCategories: ['sides'],
    color: MOD_COLORS.sides.color, textColor: MOD_COLORS.sides.textColor,
    subcats: [{ id: 'sides-mod-items', label: 'Sides', items: [
      { label: 'Dressing', id: 'dressing',     price: 0 },
      { label: 'Ranch',    id: 'ranch-sides',  price: 0 },
      { label: 'Croutons', id: 'croutons',     price: 0 },
      { label: 'Cheese',   id: 'cheese-sides', price: 1.00 },
      { label: 'Bacon',    id: 'bacon-sides',  price: 2.00 },
      { label: 'Onion',    id: 'onion-sides',  price: 0 },
      { label: 'Tomato',   id: 'tomato-sides', price: 0 },
    ]}],
  },
  {
    id: 'mod-drinks', label: 'DRINKS', menuCategories: ['drinks'],
    color: MOD_COLORS.drinks.color, textColor: MOD_COLORS.drinks.textColor,
    subcats: [{ id: 'drinks-mod-items', label: 'Drinks', items: [
      { label: 'Ice',    id: 'ice',    price: 0 },
      { label: 'Lemon',  id: 'lemon',  price: 0 },
      { label: 'Straw',  id: 'straw',  price: 0 },
      { label: 'Lid',    id: 'lid',    price: 0 },
    ]}],
  },
];

// ── Runtime filter: return HexNav data for given menu category IDs ──
export function getModHexData(categoryIds) {
  return ALL_MOD_CATEGORIES.filter(function(cat) {
    return cat.menuCategories.indexOf('*') !== -1 ||
      cat.menuCategories.some(function(c) { return categoryIds.indexOf(c) !== -1; });
  });
}

// ── Check if any selected category is pizza (for placement flow) ──
export function hasPizzaCategory(categoryIds) {
  return categoryIds.indexOf('pizza') !== -1;
}

export { MOD_COLORS };