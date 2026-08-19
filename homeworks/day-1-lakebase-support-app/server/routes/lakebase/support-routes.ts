import type { Application, Request, Response } from 'express';
import { z } from 'zod';

const STATUS_VALUES = ['open', 'in_progress', 'resolved'] as const;
const PRIORITY_VALUES = ['low', 'medium', 'high'] as const;

const TicketStatus = z.enum(STATUS_VALUES);
const TicketPriority = z.enum(PRIORITY_VALUES);

const CreateTicketBody = z
  .object({
    title: z
      .string()
      .trim()
      .min(3, 'Title must have at least 3 characters.')
      .max(160, 'Title must have at most 160 characters.'),
    priority: TicketPriority,
    created_by: z
      .string()
      .trim()
      .min(2, 'Created by must have at least 2 characters.')
      .max(80, 'Created by must have at most 80 characters.'),
  })
  .strict();

const CreateMessageBody = z
  .object({
    message_text: z
      .string()
      .trim()
      .min(1, 'Message cannot be empty.')
      .max(2000, 'Message must have at most 2000 characters.'),
    author: z
      .string()
      .trim()
      .min(2, 'Author must have at least 2 characters.')
      .max(80, 'Author must have at most 80 characters.'),
  })
  .strict();

const UpdateStatusBody = z.object({ status: TicketStatus }).strict();

const TicketFilters = z
  .object({
    status: TicketStatus.optional(),
    priority: TicketPriority.optional(),
  })
  .strict();

interface LakebaseResult {
  rows: Record<string, unknown>[];
}

interface AppKitWithLakebase {
  lakebase: {
    query(text: string, params?: unknown[]): Promise<LakebaseResult>;
  };
  server: {
    extend(fn: (app: Application) => void): void;
  };
}

const CREATE_SCHEMA_SQL = 'CREATE SCHEMA IF NOT EXISTS support_app';

const CREATE_TICKETS_SQL = `
  CREATE TABLE IF NOT EXISTS support_app.tickets (
    ticket_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title TEXT NOT NULL CHECK (char_length(btrim(title)) BETWEEN 3 AND 160),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'resolved')),
    priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high')),
    created_by TEXT NOT NULL CHECK (char_length(btrim(created_by)) BETWEEN 2 AND 80),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  )
`;

const CREATE_MESSAGES_SQL = `
  CREATE TABLE IF NOT EXISTS support_app.ticket_messages (
    message_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES support_app.tickets(ticket_id) ON DELETE CASCADE,
    message_text TEXT NOT NULL CHECK (char_length(btrim(message_text)) BETWEEN 1 AND 2000),
    author TEXT NOT NULL CHECK (char_length(btrim(author)) BETWEEN 2 AND 80),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  )
`;

const CREATE_TICKET_INDEX_SQL = `
  CREATE INDEX IF NOT EXISTS idx_tickets_status_priority_created_at
  ON support_app.tickets (status, priority, created_at DESC)
`;

const CREATE_MESSAGE_INDEX_SQL = `
  CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket_created_at
  ON support_app.ticket_messages (ticket_id, created_at ASC)
`;

// Lakebase CDF needs the complete before/after row image for updates and deletes.
// These statements are safe to repeat and run as the app service principal, which
// owns the support_app schema and its tables.
const ENABLE_TICKETS_CDF_SQL = 'ALTER TABLE support_app.tickets REPLICA IDENTITY FULL';
const ENABLE_MESSAGES_CDF_SQL = 'ALTER TABLE support_app.ticket_messages REPLICA IDENTITY FULL';
const SEED_SUPPORT_DATA_SQL = `
  WITH created_tickets AS (
    INSERT INTO support_app.tickets (title, status, priority, created_by)
    SELECT seed.title, seed.status, seed.priority, seed.created_by
    FROM (
      VALUES
        ('Cannot access the analytics workspace', 'open', 'high', 'Marina Costa'),
        ('Question about cluster runtime version', 'in_progress', 'medium', 'Rafael Lima'),
        ('Dashboard export request', 'resolved', 'low', 'Beatriz Santos')
    ) AS seed(title, status, priority, created_by)
    WHERE NOT EXISTS (SELECT 1 FROM support_app.tickets)
    RETURNING ticket_id, title
  ),
  seed_messages AS (
    SELECT * FROM (
      VALUES
        ('Cannot access the analytics workspace', 'I receive a permission error when opening the analytics workspace.', 'Marina Costa'),
        ('Cannot access the analytics workspace', 'The platform team is reviewing the workspace group assignment.', 'Support team'),
        ('Question about cluster runtime version', 'Which runtime should we use for the new data quality job?', 'Rafael Lima'),
        ('Question about cluster runtime version', 'We are validating the recommended runtime against the job dependencies.', 'Support team'),
        ('Dashboard export request', 'Could the weekly dashboard be exported as a PDF for leadership?', 'Beatriz Santos'),
        ('Dashboard export request', 'The PDF export is enabled and the delivery instructions were shared.', 'Support team')
    ) AS seed(title, message_text, author)
  )
  INSERT INTO support_app.ticket_messages (ticket_id, message_text, author)
  SELECT created_tickets.ticket_id, seed_messages.message_text, seed_messages.author
  FROM created_tickets
  INNER JOIN seed_messages ON seed_messages.title = created_tickets.title
`;

function parseTicketId(value: string | string[]): number | null {
  if (Array.isArray(value)) {
    return null;
  }
  const ticketId = Number(value);
  return Number.isSafeInteger(ticketId) && ticketId > 0 ? ticketId : null;
}

function validationResponse(response: Response, message: string, issues: z.ZodIssue[]) {
  response.status(400).json({
    error: message,
    details: issues.map((issue) => issue.message),
  });
}

function isPostgresError(error: unknown): error is { code?: string } {
  return typeof error === 'object' && error !== null && 'code' in error;
}

function sendDatabaseError(response: Response, error: unknown, operation: string) {
  console.error('[support-app] ' + operation + ' failed', error);
  response.status(500).json({ error: 'Unable to ' + operation + '. Please try again.' });
}

async function initializeSupportSchema(appkit: AppKitWithLakebase) {
  await appkit.lakebase.query(CREATE_SCHEMA_SQL);
  await appkit.lakebase.query(CREATE_TICKETS_SQL);
  await appkit.lakebase.query(CREATE_MESSAGES_SQL);
  await appkit.lakebase.query(CREATE_TICKET_INDEX_SQL);
  await appkit.lakebase.query(CREATE_MESSAGE_INDEX_SQL);
  await appkit.lakebase.query(ENABLE_TICKETS_CDF_SQL);
  await appkit.lakebase.query(ENABLE_MESSAGES_CDF_SQL);
  await appkit.lakebase.query(SEED_SUPPORT_DATA_SQL);
}

async function getTicketDetail(appkit: AppKitWithLakebase, ticketId: number) {
  const ticketResult = await appkit.lakebase.query(
    `SELECT ticket_id, title, status, priority, created_by, created_at, updated_at
     FROM support_app.tickets
     WHERE ticket_id = $1`,
    [ticketId]
  );

  if (ticketResult.rows.length === 0) {
    return null;
  }

  const messagesResult = await appkit.lakebase.query(
    `SELECT message_id, ticket_id, message_text, author, created_at
     FROM support_app.ticket_messages
     WHERE ticket_id = $1
     ORDER BY created_at ASC, message_id ASC`,
    [ticketId]
  );

  return { ticket: ticketResult.rows[0], messages: messagesResult.rows };
}

export async function setupSupportRoutes(appkit: AppKitWithLakebase) {
  await initializeSupportSchema(appkit);

  appkit.server.extend((app) => {
    app.get('/api/tickets', async (request: Request, response: Response) => {
      const parsedFilters = TicketFilters.safeParse(request.query);
      if (!parsedFilters.success) {
        validationResponse(response, 'Invalid ticket filters.', parsedFilters.error.issues);
        return;
      }

      try {
        const { status, priority } = parsedFilters.data;
        const result = await appkit.lakebase.query(
          `SELECT
             t.ticket_id, t.title, t.status, t.priority, t.created_by, t.created_at, t.updated_at,
             COUNT(m.message_id)::int AS message_count,
             MAX(m.created_at) AS last_message_at
           FROM support_app.tickets AS t
           LEFT JOIN support_app.ticket_messages AS m ON m.ticket_id = t.ticket_id
           WHERE ($1::text IS NULL OR t.status = $1)
             AND ($2::text IS NULL OR t.priority = $2)
           GROUP BY t.ticket_id
           ORDER BY t.updated_at DESC, t.ticket_id DESC
           LIMIT 100`,
          [status ?? null, priority ?? null]
        );
        response.json(result.rows);
      } catch (error) {
        sendDatabaseError(response, error, 'load tickets');
      }
    });

    app.get('/api/tickets/:ticketId', async (request: Request, response: Response) => {
      const ticketId = parseTicketId(request.params.ticketId);
      if (ticketId === null) {
        response.status(400).json({ error: 'Ticket id must be a positive integer.' });
        return;
      }

      try {
        const detail = await getTicketDetail(appkit, ticketId);
        if (detail === null) {
          response.status(404).json({ error: 'Ticket not found.' });
          return;
        }
        response.json(detail);
      } catch (error) {
        sendDatabaseError(response, error, 'load ticket details');
      }
    });

    app.get('/api/stats', async (_request: Request, response: Response) => {
      try {
        const result = await appkit.lakebase.query(
          `SELECT status, COUNT(*)::int AS ticket_count
           FROM support_app.tickets
           GROUP BY status`
        );
        const byStatus = { open: 0, in_progress: 0, resolved: 0 };
        for (const row of result.rows) {
          const status = String(row.status);
          if (status === 'open' || status === 'in_progress' || status === 'resolved') {
            byStatus[status] = Number(row.ticket_count);
          }
        }
        response.json({
          total: byStatus.open + byStatus.in_progress + byStatus.resolved,
          by_status: byStatus,
        });
      } catch (error) {
        sendDatabaseError(response, error, 'load ticket statistics');
      }
    });

    app.post('/api/tickets', async (request: Request, response: Response) => {
      const parsedBody = CreateTicketBody.safeParse(request.body);
      if (!parsedBody.success) {
        validationResponse(response, 'Please correct the ticket fields.', parsedBody.error.issues);
        return;
      }

      try {
        const result = await appkit.lakebase.query(
          `INSERT INTO support_app.tickets (title, status, priority, created_by)
           VALUES ($1, 'open', $2, $3)
           RETURNING ticket_id, title, status, priority, created_by, created_at, updated_at`,
          [parsedBody.data.title, parsedBody.data.priority, parsedBody.data.created_by]
        );
        response.status(201).json(result.rows[0]);
      } catch (error) {
        sendDatabaseError(response, error, 'create ticket');
      }
    });

    app.post('/api/tickets/:ticketId/messages', async (request: Request, response: Response) => {
      const ticketId = parseTicketId(request.params.ticketId);
      if (ticketId === null) {
        response.status(400).json({ error: 'Ticket id must be a positive integer.' });
        return;
      }

      const parsedBody = CreateMessageBody.safeParse(request.body);
      if (!parsedBody.success) {
        validationResponse(response, 'Please correct the message fields.', parsedBody.error.issues);
        return;
      }

      try {
        const result = await appkit.lakebase.query(
          `INSERT INTO support_app.ticket_messages (ticket_id, message_text, author)
           VALUES ($1, $2, $3)
           RETURNING message_id, ticket_id, message_text, author, created_at`,
          [ticketId, parsedBody.data.message_text, parsedBody.data.author]
        );
        response.status(201).json(result.rows[0]);
      } catch (error) {
        if (isPostgresError(error) && error.code === '23503') {
          response.status(404).json({ error: 'Ticket not found.' });
          return;
        }
        sendDatabaseError(response, error, 'add message');
      }
    });

    app.patch('/api/tickets/:ticketId/status', async (request: Request, response: Response) => {
      const ticketId = parseTicketId(request.params.ticketId);
      if (ticketId === null) {
        response.status(400).json({ error: 'Ticket id must be a positive integer.' });
        return;
      }

      const parsedBody = UpdateStatusBody.safeParse(request.body);
      if (!parsedBody.success) {
        validationResponse(response, 'Status must be open, in progress, or resolved.', parsedBody.error.issues);
        return;
      }

      try {
        const result = await appkit.lakebase.query(
          `UPDATE support_app.tickets
           SET status = $1, updated_at = NOW()
           WHERE ticket_id = $2
           RETURNING ticket_id, title, status, priority, created_by, created_at, updated_at`,
          [parsedBody.data.status, ticketId]
        );
        if (result.rows.length === 0) {
          response.status(404).json({ error: 'Ticket not found.' });
          return;
        }
        response.json(result.rows[0]);
      } catch (error) {
        sendDatabaseError(response, error, 'update ticket status');
      }
    });
  });
}
