import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Textarea,
} from '@databricks/appkit-ui/react';
import { CircleAlert, MessageSquarePlus, Plus, RefreshCw, Ticket } from 'lucide-react';

type TicketStatus = 'open' | 'in_progress' | 'resolved';
type TicketPriority = 'low' | 'medium' | 'high';
type TicketStatusFilter = TicketStatus | 'all';
type TicketPriorityFilter = TicketPriority | 'all';
type BadgeVariant = 'default' | 'destructive' | 'secondary' | 'outline';

interface TicketSummary {
  ticket_id: number;
  title: string;
  status: TicketStatus;
  priority: TicketPriority;
  created_by: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message_at: string | null;
}

type Ticket = Omit<TicketSummary, 'message_count' | 'last_message_at'>;

interface TicketMessage {
  message_id: number;
  ticket_id: number;
  message_text: string;
  author: string;
  created_at: string;
}

interface TicketDetail {
  ticket: Ticket;
  messages: TicketMessage[];
}

interface TicketStats {
  total: number;
  by_status: Record<TicketStatus, number>;
}

const EMPTY_STATS: TicketStats = {
  total: 0,
  by_status: { open: 0, in_progress: 0, resolved: 0 },
};

function formatStatus(status: TicketStatus) {
  return status === 'in_progress' ? 'In progress' : status.charAt(0).toUpperCase() + status.slice(1);
}

function statusBadgeVariant(status: TicketStatus): BadgeVariant {
  if (status === 'open') return 'secondary';
  if (status === 'in_progress') return 'default';
  return 'outline';
}

function priorityBadgeVariant(priority: TicketPriority): BadgeVariant {
  if (priority === 'high') return 'destructive';
  if (priority === 'medium') return 'secondary';
  return 'outline';
}

function formatDate(value: string | null) {
  if (!value) return 'No messages yet';
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function statusFilterFromValue(value: string): TicketStatusFilter {
  return value === 'open' || value === 'in_progress' || value === 'resolved' ? value : 'all';
}

function priorityFilterFromValue(value: string): TicketPriorityFilter {
  return value === 'low' || value === 'medium' || value === 'high' ? value : 'all';
}

function ticketStatusFromValue(value: string): TicketStatus {
  return value === 'open' || value === 'in_progress' || value === 'resolved' ? value : 'open';
}

function ticketPriorityFromValue(value: string): TicketPriority {
  return value === 'low' || value === 'medium' || value === 'high' ? value : 'medium';
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const body: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    const message =
      typeof body === 'object' && body !== null && 'error' in body && typeof body.error === 'string'
        ? body.error
        : 'The request could not be completed.';
    throw new Error(message);
  }

  return body as T;
}

export default function App() {
  const [tickets, setTickets] = useState<TicketSummary[]>([]);
  const [stats, setStats] = useState<TicketStats>(EMPTY_STATS);
  const [statusFilter, setStatusFilter] = useState<TicketStatusFilter>('all');
  const [priorityFilter, setPriorityFilter] = useState<TicketPriorityFilter>('all');
  const [selectedTicket, setSelectedTicket] = useState<TicketDetail | null>(null);
  const [selectedTicketId, setSelectedTicketId] = useState<number | null>(null);
  const [statusDraft, setStatusDraft] = useState<TicketStatus>('open');
  const [listLoading, setListLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showTicketForm, setShowTicketForm] = useState(false);
  const [ticketTitle, setTicketTitle] = useState('');
  const [ticketPriority, setTicketPriority] = useState<TicketPriority>('medium');
  const [ticketCreator, setTicketCreator] = useState('');
  const [messageText, setMessageText] = useState('');
  const [messageAuthor, setMessageAuthor] = useState('');

  const loadDashboard = useCallback(async () => {
    setListLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (statusFilter !== 'all') params.set('status', statusFilter);
    if (priorityFilter !== 'all') params.set('priority', priorityFilter);
    const suffix = params.size > 0 ? '?' + params.toString() : '';

    try {
      const [ticketRows, ticketStats] = await Promise.all([
        fetchJson<TicketSummary[]>('/api/tickets' + suffix),
        fetchJson<TicketStats>('/api/stats'),
      ]);
      setTickets(ticketRows);
      setStats(ticketStats);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load support tickets.');
    } finally {
      setListLoading(false);
    }
  }, [priorityFilter, statusFilter]);

  const selectTicket = useCallback(async (ticketId: number) => {
    setSelectedTicketId(ticketId);
    setDetailLoading(true);
    setError(null);

    try {
      const detail = await fetchJson<TicketDetail>('/api/tickets/' + ticketId);
      setSelectedTicket(detail);
      setStatusDraft(detail.ticket.status);
    } catch (loadError) {
      setSelectedTicket(null);
      setError(loadError instanceof Error ? loadError.message : 'Unable to load ticket details.');
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDashboard();
  }, [loadDashboard]);

  async function createTicket(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setActionLoading('ticket');
    setError(null);

    try {
      const created = await fetchJson<Ticket>('/api/tickets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: ticketTitle,
          priority: ticketPriority,
          created_by: ticketCreator,
        }),
      });
      setTicketTitle('');
      setTicketPriority('medium');
      setTicketCreator('');
      setShowTicketForm(false);
      await loadDashboard();
      await selectTicket(created.ticket_id);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : 'Unable to create ticket.');
    } finally {
      setActionLoading(null);
    }
  }

  async function addMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedTicketId) return;

    setActionLoading('message');
    setError(null);

    try {
      await fetchJson<TicketMessage>('/api/tickets/' + selectedTicketId + '/messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message_text: messageText, author: messageAuthor }),
      });
      setMessageText('');
      setMessageAuthor('');
      await Promise.all([selectTicket(selectedTicketId), loadDashboard()]);
    } catch (messageError) {
      setError(messageError instanceof Error ? messageError.message : 'Unable to add message.');
    } finally {
      setActionLoading(null);
    }
  }

  async function updateStatus() {
    if (!selectedTicketId) return;

    setActionLoading('status');
    setError(null);

    try {
      await fetchJson<Ticket>('/api/tickets/' + selectedTicketId + '/status', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: statusDraft }),
      });
      await Promise.all([selectTicket(selectedTicketId), loadDashboard()]);
    } catch (statusError) {
      setError(statusError instanceof Error ? statusError.message : 'Unable to update ticket status.');
    } finally {
      setActionLoading(null);
    }
  }

  return (
    <main className="min-h-screen bg-background p-4 md:p-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-col gap-4 border-b pb-6 md:flex-row md:items-end md:justify-between">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Ticket className="h-4 w-4" />
              <span>Databricks AI Bootcamp / Day 1</span>
            </div>
            <h1 className="text-3xl font-semibold tracking-tight">Support operations console</h1>
            <p className="max-w-2xl text-muted-foreground">
              Operational tickets and messages stored in Lakebase schema <code>support_app</code>.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => void loadDashboard()} disabled={listLoading}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Refresh
            </Button>
            <Button onClick={() => setShowTicketForm((open) => !open)}>
              <Plus className="mr-2 h-4 w-4" />
              New ticket
            </Button>
          </div>
        </header>

        {error && (
          <Alert variant="destructive">
            <CircleAlert className="h-4 w-4" />
            <AlertTitle>Action needs attention</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <section aria-label="Ticket statistics" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatisticCard label="All tickets" value={stats.total} detail="Source: Lakebase" />
          <StatisticCard label="Open" value={stats.by_status.open} detail="Awaiting work" />
          <StatisticCard label="In progress" value={stats.by_status.in_progress} detail="Actively handled" />
          <StatisticCard label="Resolved" value={stats.by_status.resolved} detail="Completed work" />
        </section>

        {showTicketForm && (
          <Card>
            <CardHeader>
              <CardTitle>
                <h2>Create a support ticket</h2>
              </CardTitle>
              <CardDescription>All fields are required. The ticket starts with status Open.</CardDescription>
            </CardHeader>
            <CardContent>
              <form
                className="grid gap-4 md:grid-cols-3"
                onSubmit={(event) => {
                  void createTicket(event);
                }}
              >
                <div className="space-y-2 md:col-span-3">
                  <Label htmlFor="ticket-title">Title</Label>
                  <Input
                    id="ticket-title"
                    value={ticketTitle}
                    onChange={(event) => setTicketTitle(event.target.value)}
                    placeholder="Describe the support request"
                    minLength={3}
                    maxLength={160}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="ticket-priority">Priority</Label>
                  <Select
                    value={ticketPriority}
                    onValueChange={(value) => setTicketPriority(ticketPriorityFromValue(value))}
                  >
                    <SelectTrigger id="ticket-priority" aria-label="Ticket priority">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="low">Low</SelectItem>
                      <SelectItem value="medium">Medium</SelectItem>
                      <SelectItem value="high">High</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2 md:col-span-2">
                  <Label htmlFor="ticket-creator">Created by</Label>
                  <Input
                    id="ticket-creator"
                    value={ticketCreator}
                    onChange={(event) => setTicketCreator(event.target.value)}
                    placeholder="Your name"
                    minLength={2}
                    maxLength={80}
                    required
                  />
                </div>
                <div className="flex items-center gap-2 md:col-span-3">
                  <Button type="submit" disabled={actionLoading === 'ticket'}>
                    {actionLoading === 'ticket' ? 'Creating...' : 'Create ticket'}
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => setShowTicketForm(false)}>
                    Cancel
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        )}

        <section className="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
          <Card>
            <CardHeader className="space-y-4">
              <div>
                <CardTitle>
                  <h2>Tickets</h2>
                </CardTitle>
                <CardDescription>
                  Filter the operational queue, then select a ticket for its conversation.
                </CardDescription>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="status-filter">Status</Label>
                  <Select value={statusFilter} onValueChange={(value) => setStatusFilter(statusFilterFromValue(value))}>
                    <SelectTrigger id="status-filter" aria-label="Filter tickets by status">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All statuses</SelectItem>
                      <SelectItem value="open">Open</SelectItem>
                      <SelectItem value="in_progress">In progress</SelectItem>
                      <SelectItem value="resolved">Resolved</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="priority-filter">Priority</Label>
                  <Select
                    value={priorityFilter}
                    onValueChange={(value) => setPriorityFilter(priorityFilterFromValue(value))}
                  >
                    <SelectTrigger id="priority-filter" aria-label="Filter tickets by priority">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All priorities</SelectItem>
                      <SelectItem value="low">Low</SelectItem>
                      <SelectItem value="medium">Medium</SelectItem>
                      <SelectItem value="high">High</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {listLoading ? (
                <div className="space-y-3">
                  {[1, 2, 3].map((item) => (
                    <Skeleton key={item} className="h-14 w-full" />
                  ))}
                </div>
              ) : tickets.length === 0 ? (
                <Empty>
                  <EmptyHeader>
                    <EmptyTitle>No tickets match these filters</EmptyTitle>
                    <EmptyDescription>Change a filter or create the first ticket in this view.</EmptyDescription>
                  </EmptyHeader>
                </Empty>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Ticket</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Priority</TableHead>
                      <TableHead className="text-right">Messages</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tickets.map((ticket) => (
                      <TableRow
                        key={ticket.ticket_id}
                        className="cursor-pointer"
                        aria-selected={selectedTicketId === ticket.ticket_id}
                        onClick={() => void selectTicket(ticket.ticket_id)}
                      >
                        <TableCell>
                          <div className="font-medium">{ticket.title}</div>
                          <div className="text-xs text-muted-foreground">
                            Opened by {ticket.created_by} / {formatDate(ticket.created_at)}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant={statusBadgeVariant(ticket.status)}>{formatStatus(ticket.status)}</Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant={priorityBadgeVariant(ticket.priority)}>{ticket.priority}</Badge>
                        </TableCell>
                        <TableCell className="text-right">{ticket.message_count}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>
                <h2>Ticket detail</h2>
              </CardTitle>
              <CardDescription>Messages and status changes are saved directly to Lakebase.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              {detailLoading ? (
                <div className="space-y-3">
                  <Skeleton className="h-8 w-3/4" />
                  <Skeleton className="h-20 w-full" />
                  <Skeleton className="h-20 w-full" />
                </div>
              ) : selectedTicket ? (
                <>
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <h2 className="text-xl font-semibold">{selectedTicket.ticket.title}</h2>
                        <p className="text-sm text-muted-foreground">
                          Created by {selectedTicket.ticket.created_by} / {formatDate(selectedTicket.ticket.created_at)}
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <Badge variant={statusBadgeVariant(selectedTicket.ticket.status)}>
                          {formatStatus(selectedTicket.ticket.status)}
                        </Badge>
                        <Badge variant={priorityBadgeVariant(selectedTicket.ticket.priority)}>
                          {selectedTicket.ticket.priority}
                        </Badge>
                      </div>
                    </div>
                    <div className="flex flex-col gap-2 sm:flex-row">
                      <Select
                        value={statusDraft}
                        onValueChange={(value) => setStatusDraft(ticketStatusFromValue(value))}
                      >
                        <SelectTrigger aria-label="Ticket status" className="sm:w-48">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="open">Open</SelectItem>
                          <SelectItem value="in_progress">In progress</SelectItem>
                          <SelectItem value="resolved">Resolved</SelectItem>
                        </SelectContent>
                      </Select>
                      <Button
                        variant="outline"
                        onClick={() => void updateStatus()}
                        disabled={actionLoading === 'status'}
                      >
                        {actionLoading === 'status' ? 'Updating...' : 'Update status'}
                      </Button>
                    </div>
                  </div>

                  <div className="space-y-3">
                    <h3 className="font-medium">Conversation ({selectedTicket.messages.length})</h3>
                    {selectedTicket.messages.length === 0 ? (
                      <Empty>
                        <EmptyHeader>
                          <EmptyTitle>No messages yet</EmptyTitle>
                          <EmptyDescription>Add the first update for this ticket below.</EmptyDescription>
                        </EmptyHeader>
                      </Empty>
                    ) : (
                      selectedTicket.messages.map((message) => (
                        <div key={message.message_id} className="rounded-lg border p-3">
                          <div className="mb-1 flex items-center justify-between gap-3 text-sm">
                            <span className="font-medium">{message.author}</span>
                            <span className="text-muted-foreground">{formatDate(message.created_at)}</span>
                          </div>
                          <p className="whitespace-pre-wrap text-sm">{message.message_text}</p>
                        </div>
                      ))
                    )}
                  </div>

                  <form
                    className="space-y-3 border-t pt-5"
                    onSubmit={(event) => {
                      void addMessage(event);
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <MessageSquarePlus className="h-4 w-4" />
                      <h3 className="font-medium">Add message</h3>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="message-text">Message</Label>
                      <Textarea
                        id="message-text"
                        value={messageText}
                        onChange={(event) => setMessageText(event.target.value)}
                        placeholder="Add a clear update for the requester"
                        minLength={1}
                        maxLength={2000}
                        required
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="message-author">Author</Label>
                      <Input
                        id="message-author"
                        value={messageAuthor}
                        onChange={(event) => setMessageAuthor(event.target.value)}
                        placeholder="Your name"
                        minLength={2}
                        maxLength={80}
                        required
                      />
                    </div>
                    <Button type="submit" disabled={actionLoading === 'message'}>
                      {actionLoading === 'message' ? 'Adding...' : 'Add message'}
                    </Button>
                  </form>
                </>
              ) : (
                <Empty>
                  <EmptyHeader>
                    <EmptyTitle>Select a ticket</EmptyTitle>
                    <EmptyDescription>Choose a row to view its messages and update its status.</EmptyDescription>
                  </EmptyHeader>
                </Empty>
              )}
            </CardContent>
          </Card>
        </section>
      </div>
    </main>
  );
}

function StatisticCard({ label, value, detail }: { label: string; value: number; detail: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-3xl">{value}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-xs text-muted-foreground">{detail} / refreshed on demand</p>
      </CardContent>
    </Card>
  );
}
