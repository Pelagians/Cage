/**
 * npm run db:reset — wipe all local data and restore the demo content.
 * Safe to run while the dev server is running (it resets tables in place).
 */
import { openDatabase, resetDatabase, resolveDbPath } from "../src/lib/db/client";

const file = resolveDbPath();
const db = openDatabase(file);
resetDatabase(db);
const clips = (db.prepare("SELECT COUNT(*) AS n FROM knowledge_clips").get() as { n: number }).n;
db.close();
console.log(`Reset ${file}: demo content restored (${clips} clips).`);
