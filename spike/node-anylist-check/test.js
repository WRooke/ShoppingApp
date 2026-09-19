// AnyList reference-implementation parity check (2026-09-20).
//
// Runs the REAL, unmodified `anylist` npm package (codetheweb/anylist, v0.8.6 — the same
// project this app's Python connector was adapted from) against the exact failure case
// already characterized in docs/build-status/anylist-fault-finding-spike.md: add an item with
// a unit-bearing quantity ("500 g"), then update it to a different unit-bearing value
// ("600 g"), then re-fetch and check whether the new value landed.
//
// Purpose: rule in/out a bug in this app's own hand-rolled Python protobuf wire encoding, by
// testing whether the REAL reference client (using real `protobufjs`, not a hand-rolled
// encoder) has the same failure. Throwaway, not part of the app. TestList only.
//
// Usage: node test.js   (run from this directory; reads ../../.env for credentials)

const fs = require('fs');
const path = require('path');
const AnyList = require('anylist');

function loadEnv(envPath) {
	const out = {};
	const text = fs.readFileSync(envPath, 'utf8');
	for (const line of text.split(/\r?\n/)) {
		const trimmed = line.trim();
		if (!trimmed || trimmed.startsWith('#')) continue;
		const eq = trimmed.indexOf('=');
		if (eq === -1) continue;
		out[trimmed.slice(0, eq).trim()] = trimmed.slice(eq + 1).trim();
	}
	return out;
}

async function main() {
	const env = loadEnv(path.join(__dirname, '..', '..', '.env'));
	const email = env.ANYLIST_EMAIL;
	const password = env.ANYLIST_PASSWORD;
	const targetListName = (env.ANYLIST_TARGET_LIST_NAME || 'TestList').trim();

	if (targetListName !== 'TestList') {
		console.error(`Refusing to run: target list is ${JSON.stringify(targetListName)}, not TestList.`);
		process.exit(1);
	}
	if (!email || !password) {
		console.error('ANYLIST_EMAIL / ANYLIST_PASSWORD not found in .env');
		process.exit(1);
	}

	// Scratch credentials cache -- kept inside this throwaway directory, never the real
	// package's default (~/.anylist_credentials), and never committed.
	const credentialsFile = path.join(__dirname, '.anylist_credentials_scratch');

	const anylist = new AnyList({email, password, credentialsFile});
	console.log('Logging in...');
	await anylist.login(false); // no websocket -- one-shot script

	let lists = await anylist.getLists();
	const list = lists.find(l => l.name === targetListName);
	if (!list) {
		console.error(`List ${JSON.stringify(targetListName)} not found. Available: ${lists.map(l => l.name).join(', ')}`);
		process.exit(1);
	}
	console.log(`Found ${targetListName} (${list.items.length} items currently on it)`);

	const name = 'NODE-CHECK-' + Date.now();
	const item = anylist.createItem({name, quantity: '500 g'});
	console.log(`Adding "${name}" with quantity "500 g"...`);
	await list.addItem(item);

	lists = await anylist.getLists();
	let freshList = lists.find(l => l.identifier === list.identifier);
	let freshItem = freshList.getItemById(item.identifier);
	const afterAdd = freshItem ? freshItem.quantity : undefined;
	console.log(`After ADD: quantity = ${JSON.stringify(afterAdd)}`);

	console.log('Updating quantity to "600 g" via item.quantity = ...; item.save()...');
	freshItem.quantity = '600 g';
	await freshItem.save();

	lists = await anylist.getLists();
	freshList = lists.find(l => l.identifier === list.identifier);
	freshItem = freshList.getItemById(item.identifier);
	const afterUpdate = freshItem ? freshItem.quantity : undefined;
	console.log(`After UPDATE: quantity = ${JSON.stringify(afterUpdate)}`);

	const verdict = afterUpdate === '600 g' ? 'SUCCEEDED' : 'FAILED';
	console.log(`\n=== VERDICT: the real reference implementation ${verdict} to persist a unit-bearing update ===\n`);

	// cleanup
	if (freshItem) {
		console.log('Cleaning up test item...');
		await freshList.removeItem(freshItem);
	}

	fs.writeFileSync(
		path.join(__dirname, 'result.json'),
		JSON.stringify({name, afterAdd, afterUpdate, verdict}, null, 2),
	);

	process.exit(0);
}

main().catch(error => {
	console.error('FAILED:', error);
	process.exit(1);
});
