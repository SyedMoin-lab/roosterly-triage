import asyncpg

type Pool = asyncpg.Pool[asyncpg.Record]
